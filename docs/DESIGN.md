# Design: ha-govee-strings v1

**Status:** draft, for review. No feature code is written until this is agreed.

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

- **One hub config entry** owns a single UDP listener on 4002. Two listeners on that
  port split replies at random, which is why this replaces `govee_light_local` instead
  of running beside it.
- **Discovery:** repeated multicast scans. Each new SKU and MAC appears as a discovered
  device for the user to confirm. A device stays known when it misses a scan. Manual IPs
  are supported for strings on another subnet.
- **Per-string settings** (options flow): bulb count (required, no default), and
  enforce on/off with an interval.
- **Transport:** our own small async UDP client. `govee-local-api` reaches only 15
  bulbs, has no per-bulb brightness, and its model table is wrong for these strings. The
  protocol is small, so taking on that dependency would cost more than it saves.

## Entities, per string

| Entity | Purpose |
|---|---|
| `light.<string>` | The whole string: on/off, brightness, RGB, and color temperature where supported |
| `light.<string>_bulb_<n>` | One bulb: RGB and brightness. Turning a bulb "off" sets its brightness to 0 |
| `select.<string>_pattern` | Applies a saved pattern |
| `switch.<string>_enforce` | "HA owns the config": re-sends the known state |

All state is **assumed**: HA shows what it last sent. This is stated on the entities
(`assumed_state`), not hidden.

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
0. Capture the current patterns as saved patterns, from the palettes that set them,
   because the device can't report them.
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

## Open questions

1. Per-bulb readback over Bluetooth through HA's proxies: v2 candidate. It depends on
   the phone-Bluetooth-off test.
2. Whether enforce re-sends flicker, and whether per-bulb state survives the nightly
   off/on cycle. If it doesn't, enforce on reappearance or turn-on becomes required,
   not optional.
3. ~~Shed to Fence to Sauna (H7039, `…3C80`) does not answer discovery.~~ Resolved
   2026-11-09: that string died and was replaced. Its HA device is an orphan with no
   entities. The house has five strings, all on one subnet.
