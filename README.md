# ha-govee-strings

A Home Assistant custom integration, in HACS repository format, for **local, per-bulb control of Govee
string lights**. It uses the Govee LAN API. It needs no Govee account, no cloud and no Bluetooth.

The built-in `govee_light_local` integration controls only a whole string. These lights accept a
color and a brightness for each bulb over the LAN, through the undocumented `ptReal` command.
This integration exposes that.

**Status:** pre-alpha. Nothing is implemented yet.

## Planned (v1)

- Automatic discovery of Govee lights on the LAN
- One light entity for the whole string, plus one light entity per bulb (color and brightness)
- Actions that paint a whole pattern in one command
- Saved patterns, with a picker entity per string
- An optional "HA owns the config" mode that re-sends the known state on a timer and after a
  string comes back online

It replaces `govee_light_local` rather than running beside it, because both need the same UDP
reply port (4002).

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
