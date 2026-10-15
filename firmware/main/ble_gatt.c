#include "ble_gatt.h"

#include <string.h>

#include "e32_xfer.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "recorder.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "store.h"

void ble_store_config_init(void); /* not exported by a public header in ESP-IDF 5.4 */

#define DEVICE_NAME "ESPeak32"
#define FW_VERSION {0, 2, 0}
#define CODECS_MASK 0x03 /* PCM16 + IMA-ADPCM */
#define RECONNECT_WINDOW_MS 60000
#define MAX_REQUEST 20
#define QUEUE_DEPTH 16
#define SEND_RETRY_MS 5

static const char *TAG = "ble";

/* 8f05e6c5-7b93-4a53-b175-b3416b3a0d20 and siblings, little-endian byte order */
#define E32_UUID(b12) \
  BLE_UUID128_INIT(0x20, 0x0d, 0x3a, 0x6b, 0x41, 0xb3, 0x75, 0xb1, 0x53, 0x4a, 0x93, 0x7b, b12, 0xe6, 0x05, 0x8f)
static const ble_uuid128_t SVC_UUID = E32_UUID(0xc5);
static const ble_uuid128_t INFO_UUID = E32_UUID(0xc6);
static const ble_uuid128_t CTRL_UUID = E32_UUID(0xc7);
static const ble_uuid128_t DATA_UUID = E32_UUID(0xc8);

typedef enum { EV_CONNECT, EV_MTU, EV_REQUEST, EV_DISCONNECT } ev_type_t;
typedef struct {
  ev_type_t type;
  uint16_t mtu;
  uint8_t len;
  uint8_t data[MAX_REQUEST];
} ev_t;

static QueueHandle_t s_queue;
static e32_xfer_t s_xfer;
static uint16_t s_ctrl_handle, s_data_handle;
static volatile uint16_t s_conn = BLE_HS_CONN_HANDLE_NONE;
static volatile bool s_advertising, s_synced;
static uint8_t s_own_addr_type;

static void post(const ev_t *e) {
  if (xQueueSend(s_queue, e, 0) != pdTRUE) ESP_LOGW(TAG, "event queue full; event %d dropped", e->type);
}

/* ---- transfer engine io ---- */

static size_t io_list(void *ctx, uint32_t *ids, size_t max) {
  (void)ctx;
  size_t n = store_list(ids, max);
  uint32_t active = recorder_active_id();
  size_t out = 0;
  for (size_t i = 0; i < n; i++)
    if (ids[i] != active) ids[out++] = ids[i];
  return out;
}

static int io_stat(void *ctx, uint32_t id, uint32_t *size) {
  (void)ctx;
  if (id != 0 && id == recorder_active_id()) return E32_XFER_EBUSY;
  return store_size(id, size) == ESP_OK ? E32_XFER_OK : E32_XFER_ENOENT;
}

static int io_read(void *ctx, uint32_t id, uint32_t off, uint8_t *buf, size_t len) {
  (void)ctx;
  return store_read(id, off, buf, len) == ESP_OK ? E32_XFER_OK : E32_XFER_EIO;
}

static int io_remove(void *ctx, uint32_t id) {
  (void)ctx;
  uint32_t size;
  if (id != 0 && id == recorder_active_id()) return E32_XFER_EBUSY;
  if (store_size(id, &size) != ESP_OK) return E32_XFER_ENOENT;
  return store_delete(id) == ESP_OK ? E32_XFER_OK : E32_XFER_EIO;
}

/* Blocks until the stack takes the notification; fails only when the link is gone. */
static int io_send(void *ctx, int channel, const uint8_t *msg, size_t len) {
  (void)ctx;
  uint16_t handle = channel == E32_XFER_CTRL ? s_ctrl_handle : s_data_handle;
  while (s_conn != BLE_HS_CONN_HANDLE_NONE) {
    struct os_mbuf *om = ble_hs_mbuf_from_flat(msg, (uint16_t)len);
    if (om) {
      int rc = ble_gatts_notify_custom(s_conn, handle, om); /* consumes om */
      if (rc == 0) return 0;
      if (rc != BLE_HS_ENOMEM && rc != BLE_HS_EBUSY) return 1;
    }
    vTaskDelay(pdMS_TO_TICKS(SEND_RETRY_MS));
  }
  return 1;
}

static uint64_t io_now(void *ctx) {
  (void)ctx;
  return (uint64_t)esp_timer_get_time();
}
static uint32_t io_free(void *ctx) {
  (void)ctx;
  return (uint32_t)store_free_bytes();
}
static uint8_t io_battery(void *ctx) {
  (void)ctx;
  return 255; /* no battery sense before M4 */
}

static const e32_xfer_io_t IO = {NULL, io_list, io_stat, io_read, io_remove, io_send, io_now, io_free, io_battery};

static void xfer_task(void *arg) {
  (void)arg;
  bool busy = false;
  ev_t e;
  for (;;) {
    if (xQueueReceive(s_queue, &e, busy ? 0 : portMAX_DELAY) == pdTRUE) {
      switch (e.type) {
        case EV_CONNECT:
          e32_xfer_connect(&s_xfer, e.mtu);
          break;
        case EV_MTU:
          e32_xfer_set_mtu(&s_xfer, e.mtu);
          break;
        case EV_REQUEST:
          e32_xfer_request(&s_xfer, e.data, e.len);
          break;
        case EV_DISCONNECT:
          e32_xfer_disconnect(&s_xfer);
          break;
      }
      busy = true;
      continue;
    }
    busy = e32_xfer_pump(&s_xfer);
  }
}

/* ---- GATT ---- */

static int chr_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg) {
  (void)conn;
  (void)attr;
  (void)arg;
  if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
    uint8_t info[E32_XFER_INFO_BYTES];
    e32_xfer_info(&s_xfer, info); /* touches only constant config and the store */
    return os_mbuf_append(ctxt->om, info, sizeof info) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
  }
  if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
    ev_t e = {.type = EV_REQUEST};
    uint16_t len = 0;
    if (OS_MBUF_PKTLEN(ctxt->om) > MAX_REQUEST) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    if (ble_hs_mbuf_to_flat(ctxt->om, e.data, sizeof e.data, &len) != 0) return BLE_ATT_ERR_UNLIKELY;
    e.len = (uint8_t)len;
    post(&e);
    return 0;
  }
  return BLE_ATT_ERR_UNLIKELY;
}

static const struct ble_gatt_svc_def SERVICES[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &SVC_UUID.u,
        .characteristics =
            (struct ble_gatt_chr_def[]){
                {.uuid = &INFO_UUID.u, .access_cb = chr_access, .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_READ_ENC},
                {.uuid = &CTRL_UUID.u,
                 .access_cb = chr_access,
                 .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_ENC | BLE_GATT_CHR_F_NOTIFY,
                 .val_handle = &s_ctrl_handle},
                {.uuid = &DATA_UUID.u, .access_cb = chr_access, .flags = BLE_GATT_CHR_F_NOTIFY, .val_handle = &s_data_handle},
                {0},
            },
    },
    {0},
};

/* ---- GAP ---- */

static int gap_event(struct ble_gap_event *event, void *arg);

static void advertise(uint32_t ms) {
  struct ble_hs_adv_fields fields = {0};
  fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
  fields.uuids128 = &SVC_UUID;
  fields.num_uuids128 = 1;
  fields.uuids128_is_complete = 1;
  struct ble_hs_adv_fields rsp = {0};
  rsp.name = (const uint8_t *)DEVICE_NAME;
  rsp.name_len = strlen(DEVICE_NAME);
  rsp.name_is_complete = 1;
  struct ble_gap_adv_params params = {.conn_mode = BLE_GAP_CONN_MODE_UND, .disc_mode = BLE_GAP_DISC_MODE_GEN};

  if (ble_gap_adv_active()) ble_gap_adv_stop();
  int rc = ble_gap_adv_set_fields(&fields);
  if (rc == 0) rc = ble_gap_adv_rsp_set_fields(&rsp);
  if (rc == 0) rc = ble_gap_adv_start(s_own_addr_type, NULL, (int32_t)ms, &params, gap_event, NULL);
  s_advertising = rc == 0;
  if (rc != 0) ESP_LOGE(TAG, "advertising failed: %d", rc);
  else ESP_LOGI(TAG, "advertising for %u s", (unsigned)(ms / 1000));
}

static int gap_event(struct ble_gap_event *event, void *arg) {
  (void)arg;
  ev_t e = {0};
  struct ble_gap_conn_desc desc;
  switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
      s_advertising = false;
      if (event->connect.status != 0) {
        advertise(RECONNECT_WINDOW_MS);
        break;
      }
      s_conn = event->connect.conn_handle;
      e.type = EV_CONNECT;
      e.mtu = ble_att_mtu(s_conn);
      post(&e);
      ESP_LOGI(TAG, "connected");
      break;
    case BLE_GAP_EVENT_DISCONNECT:
      s_conn = BLE_HS_CONN_HANDLE_NONE;
      e.type = EV_DISCONNECT;
      post(&e);
      ESP_LOGI(TAG, "disconnected (reason 0x%x)", event->disconnect.reason);
      advertise(RECONNECT_WINDOW_MS);
      break;
    case BLE_GAP_EVENT_MTU:
      e.type = EV_MTU;
      e.mtu = event->mtu.value;
      post(&e);
      ESP_LOGI(TAG, "mtu %u", event->mtu.value);
      break;
    case BLE_GAP_EVENT_ADV_COMPLETE:
      s_advertising = false;
      break;
    case BLE_GAP_EVENT_ENC_CHANGE:
      ESP_LOGI(TAG, "encryption %s", event->enc_change.status == 0 ? "on" : "failed");
      break;
    case BLE_GAP_EVENT_REPEAT_PAIRING: /* the phone lost its bond: forget ours and pair again */
      if (ble_gap_conn_find(event->repeat_pairing.conn_handle, &desc) == 0)
        ble_store_util_delete_peer(&desc.peer_id_addr);
      return BLE_GAP_REPEAT_PAIRING_RETRY;
    default:
      break;
  }
  return 0;
}

static void on_sync(void) {
  if (ble_hs_util_ensure_addr(0) != 0 || ble_hs_id_infer_auto(0, &s_own_addr_type) != 0) {
    ESP_LOGE(TAG, "no usable BLE address");
    return;
  }
  s_synced = true;
}

static void on_reset(int reason) {
  s_synced = false;
  ESP_LOGE(TAG, "host reset, reason %d", reason);
}

static void host_task(void *arg) {
  (void)arg;
  nimble_port_run();
  nimble_port_freertos_deinit();
}

esp_err_t ble_start(void) {
  s_queue = xQueueCreate(QUEUE_DEPTH, sizeof(ev_t));
  if (!s_queue) return ESP_ERR_NO_MEM;
  e32_xfer_config_t cfg = {store_boot_id(), FW_VERSION, CODECS_MASK};
  e32_xfer_init(&s_xfer, &IO, &cfg);

  esp_err_t err = nimble_port_init();
  if (err != ESP_OK) return err;
  ble_hs_cfg.sync_cb = on_sync;
  ble_hs_cfg.reset_cb = on_reset;
  ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
  ble_hs_cfg.sm_io_cap = BLE_SM_IO_CAP_NO_IO; /* Just Works */
  ble_hs_cfg.sm_bonding = 1;
  ble_hs_cfg.sm_mitm = 0;
  ble_hs_cfg.sm_sc = 1;
  ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
  ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;

  ble_svc_gap_init();
  ble_svc_gatt_init();
  int rc = ble_gatts_count_cfg(SERVICES);
  if (rc == 0) rc = ble_gatts_add_svcs(SERVICES);
  if (rc == 0) rc = ble_svc_gap_device_name_set(DEVICE_NAME);
  if (rc != 0) {
    ESP_LOGE(TAG, "GATT setup failed: %d", rc);
    return ESP_FAIL;
  }
  ble_store_config_init();
  if (xTaskCreate(xfer_task, "xfer", 4096, NULL, 5, NULL) != pdPASS) return ESP_ERR_NO_MEM;
  nimble_port_freertos_init(host_task);
  return ESP_OK;
}

void ble_advertise_for(uint32_t ms) {
  if (!s_synced) {
    ESP_LOGW(TAG, "host not ready; not advertising");
    return;
  }
  if (s_conn != BLE_HS_CONN_HANDLE_NONE) return; /* the connection holds the window open */
  advertise(ms);
}

void ble_clear_bonds(void) {
  int rc = ble_store_clear();
  ESP_LOGW(TAG, "bonds cleared (%d)", rc);
}

bool ble_is_advertising(void) { return s_advertising; }
