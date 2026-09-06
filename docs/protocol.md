# ABB ChargerSync → Home Assistant: Complete Technical Specification

> **Purpose of this document:** Everything a fresh engineering session (human or AI) needs to
> build, from zero, a HACS custom integration that controls ABB Terra AC chargers through the
> cloud APIs used by the official *ABB ChargerSync* Android app (`com.abbemobility.chargersync`,
> v3.5.0, versionCode 1757000011). All facts below were obtained by decompiling the APK with
> jadx; nothing here is guessed unless explicitly marked **[UNVERIFIED]**.

---

## 0. TL;DR architecture

```
Home Assistant
   │
   ├─(1) HTTPS REST ──► https://abb-user.chargedot.com/api/…      (account, device list, cloud start/stop)
   │
   └─(2) WSS relay ──► wss://abb.api.chargedot.com:18971/ws/login  (tunnels the charger's BLE
                                                                    binary protocol as hex JSON:
                                                                    live status, max-current, start/stop)
```

* The REST API alone cannot give live power/current or set the current limit.
* The WebSocket relay carries **exactly the same binary frames** the app sends over Bluetooth LE.
  In relay mode the SDK **disables encryption** (`isEncrypted = false`), so only the simple
  plaintext frame format + legacy DES identity-auth is needed. This is the key that makes a
  pure-Python implementation feasible.

---

## 1. How the information was obtained (reproducible)

```bash
# tools
curl -L -o jadx.zip https://github.com/skylot/jadx/releases/download/v1.5.1/jadx-1.5.1.zip
unzip jadx.zip -d jadx
unzip com_abbemobility_chargersync.apk 'classes*.dex'
./jadx/bin/jadx --show-bad-code --no-res -ds out classes.dex classes3.dex classes4.dex classes5.dex classes6.dex classes7.dex
```

Relevant decompiled classes (all in `classes4.dex`):

| Purpose | Class |
|---|---|
| REST endpoints | `com.abbemobility.chargersync.networking.ApiManagerService` |
| Constants (hosts, OAuth client) | `com.abbemobility.chargersync.BuildConfig` |
| HTTP headers | `com.abbemobility.chargersync.networking.interceptors.AbbHeaderInterceptor` |
| Relay WebSocket | `com.chargedot.bluetooth.library.WebSocketClientImpl` |
| SDK facade / connection & auth flow | `com.chargedot.bluetooth.library.CDBleClient` |
| Request frame builders | `com.chargedot.bluetooth.library.RequestBodyFactory` |
| Command IDs | `com.chargedot.bluetooth.library.CMD` |
| Response frame parser | `com.chargedot.bluetooth.library.response.CDBleResponse` |
| Individual response parsers | `com.chargedot.bluetooth.library.response.*Response` |
| App-side wrapper | `com.abbemobility.chargersync.managers.AbbBluetoothClient` |
| Status enum | `com.abbemobility.chargersync.data.enums.ChargerStatus` |

---

## 2. Cloud REST API

### 2.1 Constants (from `BuildConfig`)

```
API_HOST       = https://abb-user.chargedot.com/
API_VERSION    = v2
CLIENT_ID      = 3710400e-1c02-4175-84ea-40a227c0dcf6
CLIENT_SECRET  = f1a6d022-8a8e-453c-862e-ba0d3c5b4521
WEBSOCKET_HOST = wss://abb.api.chargedot.com:18971
APP VERSION    = 3.5.0
```

### 2.2 Headers

* `Authorization: Bearer <access_token>` (all endpoints except `api/oauth/token`)
* `X-APP-VERSION: 3.5.0` (sent by the app on every request; include it)
* `Accept: application/json`, optionally `Accept-Language`

### 2.3 Authentication (OAuth2 password grant)

`POST api/oauth/token` — `application/x-www-form-urlencoded`

| field | value |
|---|---|
| grant_type | `password` |
| client_id | CLIENT_ID |
| client_secret | CLIENT_SECRET |
| username | account e-mail |
| password | account password |

Refresh: same endpoint with `grant_type=refresh_token`, `client_id`, `client_secret`, `refresh_token`.

Response JSON (`be.appwise.networking.model.AccessToken`):
`{ "access_token": str, "refresh_token": str, "expires_in": long, "token_type": str, "id": int }`

### 2.4 Endpoints (complete list from `ApiManagerService`)

Path is relative to API_HOST. `{id}` = numeric charger id from `/devices`.

| Method | Path | Notes |
|---|---|---|
| GET | `api/v2/users/me` | → User; **`id` is needed for charger identity-auth** |
| POST | `api/v2/users/me` | update user (body `UpdateUserRequest`) |
| DELETE | `api/v2/users/me` | delete account |
| GET/POST | `api/v2/users/me/app-settings` | notification settings |
| POST | `api/v2/users/me/password` | form: password,newPassword,confirmPassword |
| POST | `api/v2/users/register` | form: email,password,confirmPassword,name,localTime,timeZone |
| POST | `api/v2/users/verify` | form: token |
| POST | `api/v2/forgot-password` | form: email |
| POST | `api/v2/verify-reset-password-code` | form: email, code |
| POST | `api/v2/reset-password` | JSON `ResetPasswordRequest` |
| **GET** | **`api/v2/devices`** | → `List<Charger>` |
| **GET** | **`api/v2/devices/{id}`** | → `Charger` |
| POST | `api/v2/devices/{id}` | JSON `UpdateChargerRequest {aliasNumber,countryCode,regionCode,softVersion,timeZone}` |
| DELETE | `api/v2/devices/{id}` | unbind |
| POST | `api/v2/devices/bind` | form: deviceNumber, pinCode |
| GET | `api/v2/devices/bound?deviceNumber=` | bound status |
| POST | `api/v2/devices/{id}/reset-pincode` | form: pinCode |
| **POST** | **`api/v2/devices/{id}/sessions/active`** | **both** "get active sessions" (→ list) **and** "start session" (→ ActiveSession) use this exact call in the app |
| **DELETE** | **`api/v2/active-sessions/{sessionId}`** | stop session (`sessionId` is the string `id` of ActiveSession) |
| GET | `api/v2/devices/{id}/sessions?page=&per_page=&startTime=&endTime=&cardNumber=&isCompanyCarSession=` | paginated history |
| POST | `api/v2/devices/{id}/sessions` | upload sessions read from charger (`UploadDeviceSessions`) |
| POST | `api/v2/devices/{id}/sessions/export` | JSON `ExportSessionsRequest {startTime, endTime, cardNumber?, format, email, isCompanyCarSession?}`; times as `yyyy-MM-dd HH:mm:ss`, `format` ∈ `pdf`/`csv`/`excel`, `email` = `users/me.authen`. The cloud e-mails the file; nothing is returned. |
| GET/POST | `api/v2/devices/{id}/sessions/auto-export` | `AutoExport {enabled, format, cycle:int, email, cardNumber?, isCompanyCarSession?, userId}`; monthly report mailed on the first day of the month |
| POST | `api/v2/sessions/{id}` | toggle company-car flag |
| GET | `api/v2/devices/{id}/trends?startTime=&endTime=&type=&cardNumber=&isCompanyCarSession=` | statistics |
| GET/POST | `api/v2/devices/{id}/price` | `EnergyPlan {open: 1=flat/2=time-of-use, currencyType, averagePrice, onPeakSt/Et/Price, midPeakSt/Et/Price, offPeakSt/Et/Price}`; times `HH:mm`, prices as strings; GET → 404 when unset |
| GET | `api/v2/devices/{id}/schedules` | → `List<Schedule{id,deviceId,userId,startTime,endTime,open}>` |
| POST | `api/v2/devices/{id}/schedules` | JSON `{startTime,endTime,open}` |
| POST | `api/v2/schedules/{id}` | update |
| DELETE | `api/v2/schedules/{id}` | |
| POST | `api/v2/devices/{id}/cipher` | → `{cipher:{info,secretKey}, deviceNumber, userId}` — AES key for **encrypted BLE** only; not needed for relay |
| GET | `api/v2/devices/{id}/latest-upgrade-packages` | firmware |
| GET | `api/v2/devices/upgrade-rules/upgrade|downgrade?currentVersion=&deviceNumber=&hardwareVersion=` | `{rule: {version, ruleIsForUpdate, packageInfo: {url, checksum, name, featureDetails, isMandatory, autoInstall}}}`; the app flashes packages over BLE only (0xB9 begin, charger pulls 0xBA blocks, 0xBB done) |
| GET/POST/PUT/DELETE | `api/v2/rfid-cards[/{id}]` | RFID management |
| GET | `api/v2/grid-meters` | |
| GET | `api/v2/countries`, `api/v2/countries/{code}`, `api/v2/countries/{code}/regions`, `api/v2/regions/{code}`, `api/v2/currencies` | reference data |
| GET | `api/v2/device/prefix` | list of device-number prefixes |
| GET | `api/v2/notices?deviceNumber=&type=`, `api/v2/public/notices?type=` | |
| POST | `api/v2/events/connect` | telemetry |
| POST | `api/v2/registry/notifications/token`, `api/v2/unregistry/notifications/token` | FCM |
| POST | `api/v2/bluetooth/device/logs/upload/{deviceNumber}` | |
| POST | `api/v2/devices-compatibility/{deviceNumber}` | |

### 2.5 Key JSON models (Gson field names = JSON keys)

**Charger** (`data.entities.Charger`):
`id:int, deviceNumber:str, aliasNumber:str, model:str, hardwareModel:str, hardwareVersion:str, softVersion:str, partNumber:str, online:int, status:long, chargeType:long, powerType:long, netType:long, netModule:[str], ratedCurrent:long, elecPower:long, countryCode, regionCode, address, latitude, longitude, pinCode, stationId, isPublic:bool, isLastConnected:bool, productType:int?, ports:[Port], certified:[str], support:{abb:{name,email,phone,company},installer:{…}}, compatibility:{…}, cipher:{info,secretKey}`

**Port**: `id, deviceId, deviceNumber, portNumber:str, portType, portTypeDetail, status, adjustCurrent, reduceRatio, deviceLevel, occupyUserId, stationId, detail`

**ActiveSession**: `id:str, deviceId:int, batteryId:float, cost:int, deliveredWh:str, elapsedDuration:str, maxCurrentAmps:int, startTime:float`

**Session**: `orderId:str, startTime:str, stopTime:str, duration:int, energy:float, cost:float, currencyType:int, solarEnergy:int?, chargeFinishReason:str, abnormal:int, startType:int, userType:int, userId:int, userCodeType:int, userCodeDetail:str, isCompanyCarSession:int, range:long`

**User**: `id:int, name:str, sessionId:str, timeZone:int?, currency:{…}, createdAt, accept, authen, face, forbidStatus`

Cloud `Charger.status` maps to `ChargerStatus` enum: 0 IDLE, 1 GUN_PLUGGED_IN, 2 CHARGING_WAITING, 3 RESERVED, 4 PAUSED, 5 ERROR_IN_CONFIG, 6 CHARGING, 7 RANDOM_DELAY_ACTIVE, 8 CHARGE_FINISHED, 9 CURRENT_TOO_LOW, 14 UNAVAILABLE, 15 ERROR, -1 NONE.

---

## 3. Remote-control WebSocket relay

Source: `WebSocketClientImpl` + `CDBleClient.init(...)` + `AbbBluetoothClient.initDeviceConnection`.

### 3.1 URL

```
wss://abb.api.chargedot.com:18971/ws/login?t=<sessionId from GET api/v2/users/me>&v=1&e=<account e-mail>
```
(`String.format("ws/login?t=%s&v=1&e=%s", token, email)`; e-mail is inserted raw — URL-encode it.)

**Verified on a real charger:** `t` must be the `sessionId` field of the `GET api/v2/users/me` response. Passing the OAuth access token is answered with `{"method":"login","code":1,"msg":"Authentication failed"}`.
A test host `ws://testabb.api.chargedot.com:18765/` also exists in the SDK defaults.

### 3.2 Message protocol (JSON text frames)

Server → client after connect:
```json
{"method":"login","code":0}            // code != 0 → auth failed, server closes
```

Client → charger (every command):
```json
{"method":"remote_control","to":"<deviceNumber>","data":"<UPPERCASE HEX of binary frame>"}
```

Charger → client:
```json
{"method":"remote_control","code":0,"data":{"deviceNumber":"<deviceNumber>","raw":"<HEX frame>"}}
```
* `code` 0 = ok, `code` 401 = SDK disconnects (relay auth lost).
* Responses are matched to requests **by command id** in the returned frame (there is no sequence number).

Server push:
```json
{"method":"update_device_status","data":{"status":<int>}}
```
SDK disconnects when `status ∈ {1, 3, -1}` (charger went offline). **[UNVERIFIED]** exact meaning of each value.

Keep-alive: client sends `{"method":"ping"}` every **30 s**. The SDK also arms a 10 s "no response → disconnect" timer right after connect, cleared on first `remote_control` reply; you don't have to replicate this.

### 3.3 Session flow (what `CDBleClient` does in WEBSOCKET mode)

1. Open WSS, wait for `login` code 0.
2. Send **identity auth** frame (cmd `0xFE`, see §4.4). Token field in that request = 8 zero bytes.
3. Parse response → 8-byte **session token**, firmware/hardware version. Store token; it must be
   placed in every subsequent request header and XOR'd into the checksum.
4. Send **sync time** (cmd `0xB0`). The SDK treats connection as "ready" (code 100) only after this succeeds.
5. Run commands (read status, etc.). If any response has result code **22 (token timeout)** → re-run step 2.

---

## 4. Charger binary protocol (plaintext mode, used by the relay)

All multi-byte integers are **little-endian** (`ByteUtils.byte2Int`, `fillBytes`).

### 4.1 Request frame (`RequestBodyFactory.wrap(byte,byte[])`)

```
offset len  content
0      1    0xFE   (0xAA only for cmd 0xBA / 0xD9)
1      1    command id
2      1    0x00
3      1    0x00
4      2    payload length (LE)
6      1    0x00
7      1    checksum = XOR of bytes[0..6] ⊕ all 8 token bytes ⊕ all payload bytes
8      8    session token (zeros before auth)
16     n    payload
```

### 4.2 Response frame (`CDBleResponse.process`)

```
0      1    0xFE or 0xAA           (parser resyncs to first FE/AA if garbage precedes)
1      1    command id
2      1    result code            (see 4.3)
3      1    -
4      2    payload length (LE), must be ≤ 1024
6      1    -
7      1    checksum = XOR of every byte of the frame except byte 7
8      8    token echo
16     n    payload  (parsers receive hex string starting at hex offset 32)
```

### 4.3 Result codes (`ResponseCodeEnum`)

`0` success · `17` parse error · `18` no permission · `19` service refused · `20` command does not exist · `21` command not supported · **`22` token timeout (re-authenticate)** · `80` device internal error · `81` command execution failed.

### 4.4 Identity authentication, legacy/plaintext (cmd `0xFE`)

`RequestBodyFactory.buildIdentityAuthenticationRequestBody(deviceNumber)`:

```
block = bytearray(48)
block[0:len(dn)]   = deviceNumber.replace("-", "")   (ASCII)
                     zero-padded to 20 bytes
block[20]          = 0x02
block[21]          = 0x01
block[22:22+len(u)]= str(userId)   (ASCII, userId from GET api/v2/users/me), zero-padded to 15 bytes (→ offset 37)
block[37:45]       = 0
block[45:48]       = 0
enc   = DES/ECB/PKCS5Padding(block, key=b"ucserver")   → 56 bytes (single DES, 8-byte key)
payload = bytes(130): payload[0:2] = 0x80 0x00 (LE 128); payload[2:2+56] = enc; rest zeros
frame = wrap(0xFE, payload)   with token = 8 zero bytes
```
Note: In Python, `cryptography`'s `TripleDES` with an 8-byte key equals single DES.

Response payload (`IdentityAuthResponse.process`):

```
0      1    startCode: 0xFF → auth failed
1      20   hardware version (ASCII, '#' chars stripped)
21     3    software version bytes b0,b1,b2 → "b2.b1.b0"
24     2    communication version "b0.b1"
26     8    SESSION TOKEN
```

### 4.5 Command catalogue (`CMD.java`) — all ids

| id | name | id | name |
|---|---|---|---|
| 0xA0 160 | SET_POWER_SAVING_MODE | 0xC9 201 | NFC_DEVICE_SETTINGS |
| 0xA2 162 | CONFIGURE_MAXIMUM_PHASE_IMBALANCE | 0xCA 202 | SET_WHITE_LIST |
| 0xA3 163 | QUERY_MAXIMUM_PHASE_IMBALANCE | 0xCE 206 | CE_AUTH |
| 0xA4 164 | SCHEDULED_LIMIT | 0xCF 207 | GSM_CONFIGURATION |
| 0xA6 166 | CONFIGURE_FALLBACK | 0xD0 208 | START/ACTIVE_ADD_CARD |
| 0xA7 167 | CONFIGURE_A7 | 0xD1 209 | FORCE_UNLOCK |
| 0xAA 170 | QUERY_CHARGER_TCPIP_CONFIGURATION | 0xD2 210 | CONFIGURATION_WIFI_NETWORK |
| 0xAB 171 | CONFIGURE_CHARGER_TCPIP_CONFIGURATION | 0xD3 211 | CHECK_NETWORK_STATUS |
| 0xAD 173 | QUERY_CHARGING_RECORDS_WITH_SOLAR | 0xD4 212 | CHANGE_NET_MODE |
| 0xAE 174 | QUERY_ACCUMULATED_POWER_WITH_SOLAR | 0xD6 214 | REQUEST_OCPP_SERVER_CONFIGURE |
| 0xAF 175 | QUERY_CHARGING_STATUS_WITH_SOLAR | 0xD7 215 | …_NOTIFICATION |
| **0xB0 176** | **SYNC_TIME** | 0xD8 216 | QUERY_OCPP_SERVER_CONFIGURE_STATUS |
| **0xB1 177** | **READ_SYS_INFO** | 0xD9 217 | DOWNLOAD_OCPP_SERVER_CONFIGURE |
| 0xB2 178 | SET_VOICE | 0xDA 218 | DOWNLOADING_OCPP_SERVER_CONFIGURE |
| 0xB3 179 | SET_CHARGE_MODE (schedule) | 0xDB 219 | QUERY_DEVICE_NET_CONFIG |
| **0xB4 180** | **AUTH_CHARGE (start)** | 0xDC 220 | SET_DEVICE_CONFIG_CAPACITATE |
| **0xB5 181** | **READ_STATUS** | 0xDD 221 | QUERY_DEVICE_CONFIG_CAPACITATE |
| **0xB6 182** | **STOP_CHARGE** | 0xDE 222 | SET_FOURG_MODULE_PARAM |
| 0xB7 183 | READ_HISTORY_CHARGE_RECORDER | 0xDF 223 | QUERY_FOURG_MODULE_PARAM |
| 0xB8 184 | READ_TOTAL_CHARGE | **0xE0 224** | **QUERY_POWER_PERCENT (current limit)** |
| 0xB9 185 | BEGIN_UPGRADE | 0xE1 225 | QUERY_CARD |
| 0xBA 186 | BEGIN_DOWNLOAD_UPGRADE_PACKAGE | 0xE2 226 | SET_SMART_METER |
| 0xBB 187 | DOWNLOAD_UPGRADE_PACKAGE_SUCCESS | 0xE3 227 | QUERY_SMART_METER |
| 0xBC 188 | QUERY_SYS_LOG_INFO | 0xE4 228 | QUERY_WIFI_INFO |
| 0xBD 189 | QUERY_SYS_LOG_LIST | 0xE5 229 | QUERY_METER_CONNECT_STATUS |
| 0xBF 191 | GRID_NETWORK_CONFIGURATION | 0xE6 230 | QUERY_CHARGE_MODE |
| **0xC0 192** | **POWER_CONTROL (set max current)** | 0xE7 231 | FORCE_LOCK |
| 0xC1 193 | CHARGE_POINT_BASIC_INFORMATION | 0xE8 232 | SET_MODBUS |
| 0xC2 194 | CHARGE_POINT_EMPLOY_INFORMATION | 0xE9 233 | QUERY_MODBUS |
| 0xC3 195 | POWER_NETWORK_LAYER_CONFIGURATION | 0xF0 240 | QUERY_CHARGER_CONFIGURATION |
| 0xC4 196 | ELECTRICAL_PROTECTION_SETTINGS | 0xF1..0xF6 | ELECTRIC_METER / MODBUS / IO settings |
| 0xC5 197 | SOCKET_CONFIGURATION | 0xF7 247 | DEVICE_REPORT (unsolicited push) |
| 0xC6 198 | NETWORK_OF_LAN_CONFIGURATION | 0xF9 249 | QUERY_IMEI |
| 0xC7 199 | NETWORK_OF_WIFI_CONFIGURATION | 0xFA 250 | RESET_CHARGER_POINT |
| 0xC8 200 | BLUETOOTH_DEVICE_INFORMATION | 0xFB 251 | VIN_CODE |
| | | 0xFC 252 | SMART_METER_EXTENDED |
| | | **0xFE 254** | **IDENTITY_AUTHENTICATION** |

### 4.6 Payloads of the commands needed for HA

| Command | Request payload | Response payload |
|---|---|---|
| SYNC_TIME 0xB0 | `u32 unixTime` + `u8 (tzOffsetHours + 12)` | ignore body; code 0 = ok |
| READ_SYS_INFO 0xB1 | none | `[0:20]` deviceNumber ASCII, `[20]` plugType, `[21]` manufacturer, `[22:26]` magic, `[26:28]` proto ver, `[28:31]` sw version (b2.b1.b0), `[31:51]` soft model ASCII, … |
| AUTH_CHARGE 0xB4 (start) | `00 00` | `[0]` result (0 = ok) |
| READ_STATUS 0xB5 | `00` | see below |
| STOP_CHARGE 0xB6 | `00` | code 0 = ok (parser only requires len ≥ 4) |
| POWER_CONTROL 0xC0 | `u8 port (0)`, `u8 currentAmps` | `[0]` result (0 = ok) |
| QUERY_POWER_PERCENT 0xE0 | none | `[0]` port, `[1]` maxOutputCurrent, `[2..]` outputCurrent (LE) |
| READ_TOTAL_CHARGE 0xB8 | none | accumulated energy **[UNVERIFIED layout]** |

**READ_STATUS response** (`ReadStatusResponse.process` / `processCharging`):

```
[0]  status code:
     00 idle ("In the free")      05 SuspendedEV
     01 plugged in, not charging  06 charging  ← only then the fields below follow
     02 wait charging             07 pausing
     03 reserved                  08 finished, cable still in
     04 SuspendedEVSE             0E unavailable   0F fault (then [1:3] = u16 fault code)
If status == 06:
[1]    phaseLineType (0 = single phase, else 3-phase)
[2:6]  u32 session id
[6:8]  u16 energy   /100 → kWh
[8:12] u32 voltage  /100 → V  (L1)
[12:14]u16 current  /100 → A  (L1)
 single phase:  [14:18] u32 duration s, [18] rated current A
 three phase:   [14:18] u32 V L2/100, [18:20] u16 I L2/100,
                [20:24] u32 V L3/100, [24:26] u16 I L3/100,
                [26:30] u32 duration s, [30] rated current A
```
Power (W) is not transmitted; compute `Σ V·I` per phase.

### 4.7 Encrypted mode (BLE only — documented for completeness, NOT used by relay)

Devices that advertise encryption in BLE manufacturer data use a 3-step handshake over cmd 0xFE
(`index` byte 1/2/3: client nonce → server nonce → 48-byte auth block) and then **AES-128-GCM**
(12-byte random nonce, 16-byte tag, AAD = deviceNumber padded to 20 bytes + `u16 LE firmware
version with dots removed`). Key = `cipher.secretKey` (hex) and `cipher.info` (hex, 16 bytes,
appended to 0xFE frames) from `POST api/v2/devices/{id}/cipher`. Header byte 6 becomes `0xA5`
and the header is 8 bytes (token is inside the ciphertext). Skip this entirely for the relay.

---

## 5. Home Assistant integration design

### 5.1 Repository layout (HACS)

```
ha-abb-chargersync/
├── hacs.json                     {"name":"ABB ChargerSync (Terra AC)","render_readme":true,"homeassistant":"2025.1.0"}
├── README.md
├── tools/probe.py                standalone CLI test (login → relay → read status)
└── custom_components/abb_chargersync/
    ├── manifest.json             domain abb_chargersync, config_flow true, iot_class cloud_polling,
    │                             integration_type hub, requirements [] (uses HA-bundled aiohttp + cryptography)
    ├── const.py                  DOMAIN, PLATFORMS=[sensor,binary_sensor,number,switch,button],
    │                             CONF_SCAN_INTERVAL (default 30, min 10), CONF_USE_RELAY (default True)
    ├── protocol.py               §4 – pure functions, no HA imports
    ├── api.py                    AbbCloudClient (REST) + AbbRelayClient (WSS)
    ├── coordinator.py            DataUpdateCoordinator per charger
    ├── entity.py                 base CoordinatorEntity with DeviceInfo
    ├── config_flow.py            user (email/password) + reauth + options
    ├── sensor.py / binary_sensor.py / number.py / switch.py / button.py
    ├── strings.json, translations/en.json
```

### 5.2 `api.py` behaviour

**AbbCloudClient**
* `login()`, `_refresh()` (falls back to login on failure), `ensure_token()` (refresh 60 s before `expires_in`), `request()` retries once on HTTP 401 after clearing the token.
* Helpers: `get_user()` (stores `user_id`), `get_devices()`, `get_device()`, `get_active_sessions()`, `cloud_start_session()`, `cloud_stop_session()`, `get_schedules()`, `get_sessions()`.

**AbbRelayClient** (one instance per charger)
* `connect()`: `session.ws_connect(url)`, start reader task, await `login` message (15 s timeout), start 30 s ping task.
* `_send(cmd, frame)`: register `Future` keyed by `cmd`, send JSON, await matching frame (15 s → raise *ChargerOffline*). Map result code 22 → *AuthError* (sets `authenticated=False`), other non-zero → *ApiError*.
* `authenticate()`: build §4.4 frame with `user_id`, store token/firmware, then best-effort SYNC_TIME.
* `ensure_session()` under an `asyncio.Lock`: connect if closed, authenticate if needed.
* `_command()`: `ensure_session()`, send; on *AuthError* close, re-establish, retry once.
* High-level: `read_status()`, `read_power_control()`, `set_max_current(amps)`, `start_charging()`, `stop_charging()`, `sys_info()`.
* Handle `update_device_status` (offline) and `remote_control code 401` by failing all pending futures.

### 5.3 Coordinator (`_async_update_data`, every `scan_interval` s)

1. `GET api/v2/devices/{id}` (metadata, `online`, cloud `status`), `POST …/sessions/active` (active session).
2. If relay enabled and device online: `read_status()`; re-read `read_power_control()` every 5th poll or when unknown; capture firmware/hardware from auth. On any relay error: record `relay_error`, `close()` the relay (fresh connect next poll), keep last known power-limit/firmware.
3. Commands: start/stop go via relay when available, else via cloud REST; `set_max_current` requires relay. Request refresh afterwards.
4. `async_unload_entry` closes relays.

### 5.4 Entities (unique_id = `{deviceNumber}_{key}`, `has_entity_name=True`)

| Platform | key | Source |
|---|---|---|
| sensor | `status` (enum: idle, plugged_in, waiting_for_ev, reserved, suspended_evse, suspended_ev, charging, paused, charge_finished, unavailable, fault, unknown) + attrs status_code/cloud_status/session_id/phase_type | READ_STATUS |
| sensor | `power` W (Σ V·I), `session_energy` kWh (TOTAL), `session_duration` s, `current_l1..l3` A, `voltage_l1..l3` V (L2/L3 disabled by default) | READ_STATUS |
| sensor (diag) | `rated_current`, `fault_code`, `max_current_limit` (hardware max), `relay_error` | READ_STATUS / QUERY_POWER_PERCENT |
| binary_sensor | `online` (relay ok or cloud `online`), `charging` (status 06), `plugged_in` (status 1..8) | |
| number | `max_current` slider, min 6, max = hardware `maxOutputCurrent` or cloud `ratedCurrent`, step 1 | QUERY_POWER_PERCENT / POWER_CONTROL |
| switch | `charging` on = status ∈ {02,06,07}; on→start, off→stop | |
| button | `start_charging`, `stop_charging`, `reconnect` (closes relay) | |

DeviceInfo: identifiers `(DOMAIN, deviceNumber)`, manufacturer ABB, model from `model`/`hardwareModel`, name `aliasNumber`, sw/hw version from identity-auth response (fallback cloud fields).

### 5.5 Config flow

* Step `user`: email + password → `AbbCloudClient.login(); get_user(); get_devices()`; errors `invalid_auth`, `cannot_connect`, `no_devices`; unique_id = lowercase e-mail.
* Step `reauth_confirm`: new password.
* Options: `scan_interval` (10–3600), `use_relay` (bool). Reload entry on options change.

### 5.6 Reference implementation of the core (Python, verified by local round-trip tests)

```python
CMD_SYNC_TIME=0xB0; CMD_READ_SYS_INFO=0xB1; CMD_START=0xB4; CMD_READ_STATUS=0xB5
CMD_STOP=0xB6; CMD_POWER_CONTROL=0xC0; CMD_QUERY_POWER=0xE0; CMD_AUTH=0xFE

def build_frame(cmd, payload, token):            # token: 8 bytes
    payload = payload or b""
    start = 0xAA if cmd in (0xBA, 0xD9) else 0xFE
    hdr = bytes([start, cmd, 0, 0, len(payload) & 0xFF, len(payload) >> 8, 0])
    chk = 0
    for b in hdr + token + payload: chk ^= b
    return hdr + bytes([chk]) + token + payload

def parse_frame(data):
    cmd, code = data[1], data[2]
    n = data[4] | (data[5] << 8)
    data = data[:16 + n]
    chk = 0
    for i, b in enumerate(data):
        if i != 7: chk ^= b
    assert chk == data[7]
    return cmd, code, data[8:16], data[16:]

def des_ecb_pkcs5(data, key=b"ucserver"):
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES   # >=43; else primitives.ciphers.algorithms
    from cryptography.hazmat.primitives.ciphers import Cipher, modes
    pad = 8 - len(data) % 8; data += bytes([pad]) * pad
    e = Cipher(TripleDES(key), modes.ECB()).encryptor()
    return e.update(data) + e.finalize()

def build_identity_auth(device_number, user_id):
    dn = device_number.replace("-", "").encode(); uid = str(user_id).encode()
    blk = bytearray(48); blk[:len(dn)] = dn; blk[20] = 2; blk[21] = 1; blk[22:22+len(uid)] = uid
    body = bytearray(130); body[0] = 0x80; enc = des_ecb_pkcs5(bytes(blk)); body[2:2+len(enc)] = enc
    return build_frame(CMD_AUTH, bytes(body), bytes(8))

# identity-auth response payload p: token = p[26:34] (p[0]==0xFF → failed)
# sync time payload: struct.pack("<I", int(time.time())) + bytes([tz_hours + 12])
# read status payload: b"\x00"; start: b"\x00\x00"; stop: b"\x00"; power control: bytes([0, amps])
```

Relay JSON, exactly:
```python
await ws.send_str(json.dumps({"method": "remote_control", "to": device_number, "data": frame.hex().upper()}))
# response: json["data"]["raw"] → bytes.fromhex(...) → parse_frame
```

---

## 6. Validation plan (do this before loading into HA)

`tools/probe.py` (aiohttp + cryptography):

1. `POST api/oauth/token` → print `access_token` prefix, `expires_in`.
2. `GET api/v2/users/me` → print `id`; `GET api/v2/devices` → print id/deviceNumber/online/status/ratedCurrent.
3. Open WSS URL, print every received message.
4. Send identity-auth; expect `remote_control` code 0 with `raw` starting `FEFE00…`; print hardware/software version + token.
5. Send SYNC_TIME, then READ_STATUS every 5 s; print decoded `ChargerStatus`. Plug/unplug the car to see status transitions.
6. Send QUERY_POWER_PERCENT; then POWER_CONTROL with the same current to test write path safely.

Things most likely to need adjustment on first real run (in order of probability):
* e-mail URL-encoding in the WSS query string;
* the `deviceNumber` in `remote_control.data` responses may be absent/differ — match on frame cmd only;
* `update_device_status` semantics;
* whether the relay requires the charger to be marked `online` in the cloud;
* READ_TOTAL_CHARGE and history layouts (not needed for the core entities).

---

## 7. Constraints, risks, legal

* Unofficial internal API; ABB can change endpoints, rotate the OAuth client, or rate-limit.
* Relay only works when the charger has internet (Wi-Fi/Ethernet/4G) and is bound to the account. Bluetooth-only installations cannot use it.
* The app allows only one connection per charger at a time — using HA while the app is connected may collide **[UNVERIFIED]**.
* Poll interval ≥ 10 s recommended; default 30 s.
* Credentials extracted from the app are for personal interoperability use; keep the repository's intent clear and avoid publishing derived binaries of the APK.
