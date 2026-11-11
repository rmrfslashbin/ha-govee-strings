# ha-govee-strings

A Home Assistant custom integration, in HACS repository format, for **local, per-bulb control of Govee
string lights**. It uses the Govee LAN API. It needs no Govee account, no cloud and no Bluetooth.

The built-in `govee_light_local` integration controls only a whole string. These lights accept a
color and a brightness for each bulb over the LAN, through the undocumented `ptReal` command.
This integration exposes that.

**Status:** v0.1.0, pre-alpha. Built and unit-tested; not yet run against hardware from Home Assistant.

## Features

- Discovers Govee lights on the LAN, and follows DHCP address changes.
- **Whole-string light:** on/off, brightness, RGB, and color temperature where the model
  supports it.
- **Per-bulb lights** (`Bulb 1` … `Bulb N`): RGB and brightness. Disabled by default;
  enable the ones you want. An enabled bulb belongs to the string's device, so an automation
  that targets lights by device **label or area** reaches it too. Turning one bulb off on its
  own clears the string's pattern select (it shows `unknown`) even though the other bulbs are
  unchanged. Keep bulbs disabled unless you need them, or target the whole-string entity.
- **Pattern select:** applies a saved per-bulb pattern. HA scenes can set it.
- **Enforce pattern switch:** re-sends the known state on a timer, when the string comes
  back online, and when it's turned on. It never turns a string on.
- **Actions:**
  - `govee_strings.paint`: set many bulbs in one call, e.g.
    `runs: [{bulbs: "1-15", rgb: [0, 255, 255], brightness: 60}]`.
  - `govee_strings.save_pattern`: save a pattern from a string's current state, or from an
    explicit list of bulbs.
  - `govee_strings.apply_pattern`: apply a saved pattern, with `fit: exact|repeat|truncate`.
  - `govee_strings.delete_pattern`.

It replaces `govee_light_local` rather than running beside it, because both need the same UDP
reply port (4002). Setup refuses to start while `govee_light_local` is loaded.

**State is assumed.** The lights don't report per-bulb colors, so HA shows what it last sent.
Changes made in the Govee app aren't seen. Turn on "Enforce pattern" if HA should own the look.

## Verified hardware

| Model | Bulbs tested | Per-bulb color | Per-bulb brightness |
|---|---|---|---|
| H7021 | 30 | yes | yes |
| H7025 | 15 | yes | yes |
| H7039 | 45 | yes | yes |

The bulb count is set per string, because the same model ships in different lengths.

## Installing

Home Assistant 2026.11 replaced HACS with the built-in Marketplace. Add this repository
there as a custom repository. (Not yet verified end to end. Older installs use HACS the
same way.)

## Requirements

**LAN Control** must be enabled for each light in the Govee app.

## License

MIT. See [LICENSE](LICENSE).
