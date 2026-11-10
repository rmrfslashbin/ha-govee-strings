# Design: ha-govee-strings v1

**Status:** approved 2026-11-09 and built as v0.1.0. It has not been tested against hardware or a live HA yet.

## Goal

Local, per-bulb control of Govee string lights from Home Assistant. It needs no Govee
account, no cloud and no Bluetooth, and it replaces the built-in `govee_light_local`.

## What the hardware does (verified 2026-11-09)

| Model | Bulbs (as installed) | Per-bulb color | Per-bulb brightness |
|---|---|---|---|
| H7021 | 30 | yes | yes |
| H7025 | 15 | yes | yes |
| H7039 | 45 | yes | yes |

- Per-bulb writes are raw BLE frames sent inside the undocumented `ptReal` LAN command
  (`custom_components/govee_strings/protocol.py`).
- The device does not acknowledge them.
- After a per-bulb write, `devStatus` keeps reporting a stale color. Brightness and power
  stay accurate.
- No LAN query returns per-bulb state. The Govee app shows it, by a route not yet
  identified: Bluetooth or the cloud.
- Bulb count is a property of the string, not the model, and is not discoverable.
- Discovery over multicast is lossy: one of two back-to-back scans missed a string.

## Architecture

- **One config entry per string**, each with its own bulb count. All of them share one
  UDP transport that owns 4002, reference-counted across entries and config flows.
  (The draft said one hub entry. Per-string entries give HA-native discovery, options and
  reload for free.)
- **Port conflict is a hard stop, never a quiet split.** The transport binds without
  `SO_REUSEADDR`/`SO_REUSEPORT`: on Linux, two UDP sockets that both set `SO_REUSEADDR`
  may share a port. Setup also refuses while a `govee_light_local` entry is loaded. Both
  cases surface as "port in use" (setup retry, or a flow abort).
- **Discovery:** a scan is sent 3 times over 3 s, because multicast is lossy. It runs
  every 5 minutes while any entry is loaded. A new string raises an integration
  discovery flow. A known string that changed IP (DHCP) is updated without a reload.
  Manual IPs are supported.
- **Per-string settings:** bulb count, required when the string is added (no default),
  and the enforce interval. Both are in the options flow, and a change reloads the entry.
- **Transport:** our own small async UDP client. `govee-local-api` reaches only 15
  bulbs, has no per-bulb brightness, and its model table is wrong for these strings.
- **Status:** `devStatus` every 30 s, for power and whole-string brightness only. Three
  misses in a row mark the string unavailable.
- **Setup never sends anything to a light.**

## Entities, per string

| Entity | Purpose |
|---|---|
| `light.<string>` | The whole string: on/off, brightness, RGB, and color temperature where supported |
| `light.<string>_bulb_<n>` | One bulb: RGB and brightness. "Off" paints it black, and "on" restores its color. **Disabled by default**, see below |
| `select.<string>_pattern` | Shows the applied pattern; picking one applies it. HA scenes can set it, so a scene can hold a per-bulb look |
| `switch.<string>_enforce` | "HA owns the config": re-sends the known state |

All state is **assumed**: HA shows what it last sent. This is stated on the entities
(`assumed_state`), not hidden. Per-bulb state is persisted in `.storage`, so it
survives an HA restart.

**Why per-bulb lights are disabled by default:** label and device targets include every
enabled entity of a device. The sunset/sunrise automation targets a device label, so
with bulbs enabled it would send up to 56 per-bulb commands per string, twice a day.
Disabled entities are skipped. A paint that changes nothing sends nothing and keeps the
active pattern.

## Actions

- `govee_strings.paint`: set many bulbs in one call. It takes a list of `{bulbs, rgb,
  brightness}` runs, and bulbs with the same color share one frame.
- `govee_strings.save_pattern`, `apply_pattern` and `delete_pattern`.

## Patterns

- Stored in the integration's `.storage` file, keyed by name. Each pattern has a bulb
  count and a list of `{rgb, brightness}` per bulb.
- Applying a pattern to a string with a different bulb count is refused, unless
  `fit: repeat|truncate` is passed.
- No animation in v1.

## Enforce ("HA owns the config")

- Re-sends the known state every N minutes (default 5) and whenever a string reappears
  in discovery after missing scans (for example, after a power cut).
- It never turns a string on: a string that is off stays off.
- Changes made in the Govee app are overwritten when this is on. That is the intent.
- Whether re-sending the same colors causes visible flicker is still to be checked on
  hardware.

## Cutover and rollback (the risky part)

Starting state (2026-11-09):
- Entity IDs: `light.front_porch_string_lights`, `light.back_porch_string_lights`,
  `light.sauna_string_lights`, `light.backyard_loop_string_lights` and
  `light.backyard_fence_string_lights`.
- Every string is showing a per-bulb pattern Robert chose, set by hand over LAN.
- The sunset/sunrise automation targets devices by **label** (`outdoor_lights`,
  `string_lights`), not by entity ID.

Steps:
0. Seed all **four** saved patterns from `govee-patterns/` in the (private) workspace
   repo: `november-night-45` (Loop, Fence), `november-night-30` (Back Porch),
   `front-porch-colorful-30` and `sauna-alpine-winter-15`. The device can't report
   them. Both 30-bulb strings need their own pattern.
1. Disable the `govee_light_local` config entry. Its sockets close, freeing 4002.
2. Rename its light entities aside (`*_core_old`) so the new ones can take the existing
   entity IDs. Dashboards and automations then keep working.
3. Add this integration and confirm each string. **Setup never sends anything to a
   light**, and enforce is off by default, so the patterns survive cutover.
4. Put the `outdoor_lights` and `string_lights` labels on the new devices. Without
   them, the sunset/sunrise automation silently stops driving the strings. Verify
   the automation's targets resolve.
5. Soak period. Then delete the old entry. That also removes the orphan device of the
   dead H7039 `…3C80`, which `govee_light_local` refuses to remove on its own.

**Rollback:** disable this entry, rename the IDs back, and re-enable the old one.

Each step is a separate, approved batch, and its blast radius is stated before it runs.

## Out of scope for v1

Govee app scenes (they need the cloud), music mode, animation, per-bulb readback, and
Bluetooth transport.

## Not yet verified against hardware

- Bulb "off" as black (`00 00 00`). The frame is the same one used for colors, but
  black was never sent in the spike.
- Several frames back to back at 250 ms. Each spike test sent frames one at a time.

## Open questions

1. Per-bulb readback over Bluetooth through HA's proxies: v2 candidate. It depends on
   the phone-Bluetooth-off test.
2. Whether enforce re-sends flicker, and whether per-bulb state survives the nightly
   off/on cycle. If it doesn't, enforce on reappearance or turn-on becomes required,
   not optional.
3. ~~Shed to Fence to Sauna (H7039, `…3C80`) does not answer discovery.~~ Resolved
   2026-11-09: that string died and was replaced. Its HA device is an orphan with no
   entities. The house has five strings, all on one subnet.
