# DNS notes

Derived from proxied connections: the name the client asked for (TLS SNI / HTTP `Host`)
and the peer address the proxy connected to. This is an observation of captured traffic,
not a resolver log - for real DNS queries run `catcher pcap start` on a rooted device.

| Host | Recorded peer IPs | Exchanges | Sessions | First seen | Last seen |
| --- | --- | --- | --- | --- | --- |
| fed.gold0029.gameloft.com | - | 356 | 20261125-210955, frida-unpin | 2026-11-25T20:10:23.403567Z | 2026-11-25T23:33:45.066717Z |
| iris16-gold.gameloft.com | - | 356 | 20261125-210955, frida-unpin | 2026-11-25T20:10:24.008214Z | 2026-11-25T23:33:45.467641Z |
| cdp.cloud.unity3d.com | - | 18 | 20261125-210955, frida-unpin | 2026-11-25T20:55:09.810082Z | 2026-11-25T23:34:46.273885Z |
| googleads.g.doubleclick.net | - | 6 | 20261125-210955 | 2026-11-25T20:53:32.184260Z | 2026-11-25T20:54:13.601503Z |
| ae.iads.unity3d.com | - | 2 | 20261125-210955 | 2026-11-25T20:53:58.909720Z | 2026-11-25T20:54:48.771413Z |
| api.helpshift.com | - | 2 | frida-unpin | 2026-11-25T23:23:29.299832Z | 2026-11-25T23:23:29.408086Z |
| firebase-settings.crashlytics.com | - | 2 | frida-unpin | 2026-11-25T23:22:42.160542Z | 2026-11-25T23:22:42.629493Z |
| pagead2.googlesyndication.com | - | 2 | 20261125-210955 | 2026-11-25T21:55:10.718782Z | 2026-11-25T22:32:40.242343Z |
| config.uca.cloud.unity3d.com | - | 1 | frida-unpin | 2026-11-25T23:22:48.029085Z | 2026-11-25T23:22:48.029085Z |
| firebaseinstallations.googleapis.com | - | 1 | frida-unpin | 2026-11-25T23:22:42.159885Z | 2026-11-25T23:22:42.159885Z |
| firebaselogging-pa.googleapis.com | - | 1 | frida-unpin | 2026-11-25T23:23:37.354226Z | 2026-11-25T23:23:37.354226Z |
| firebaselogging.googleapis.com | - | 1 | 20261125-210955 | 2026-11-25T20:53:50.379447Z | 2026-11-25T20:53:50.379447Z |
| o-iab-notifications.mediation.unity3d.com | - | 1 | 20261125-210955 | 2026-11-25T20:54:43.689714Z | 2026-11-25T20:54:43.689714Z |

`Recorded peer IPs` comes from the proxy's resolved server connection. Sessions captured before that field existed show `-`; `catcher pcap start` records real DNS at the wire level.
