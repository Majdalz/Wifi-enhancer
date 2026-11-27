import json
import unittest

from wifi_enhancer.analysis import analyze, congestion_24
from wifi_enhancer.latency import parse_ping_times
from wifi_enhancer.scanner import (Network, demo_networks, parse_netsh, parse_nmcli,
                                   parse_system_profiler)

NMCLI = r"""*:HomeNet:AA\:BB\:CC\:DD\:EE\:01:6:2437 MHz:72:WPA2
 :Cafe\:Guest:AA\:BB\:CC\:DD\:EE\:02:36:5180 MHz:40:
 ::AA\:BB\:CC\:DD\:EE\:03:11:2462 MHz:20:WPA1 WPA2
"""

NETSH = """
SSID 1 : HomeNet
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 88%
         Radio type         : 802.11ax
         Channel            : 6
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 60%
         Channel            : 44
SSID 2 : Free WiFi
    Authentication          : Open
    BSSID 1                 : aa:bb:cc:dd:ee:03
         Signal             : 30%
         Channel            : 1
"""

NETSH_IFACE = """
    State                  : connected
    SSID                   : HomeNet
    BSSID                  : aa:bb:cc:dd:ee:01
"""

MAC = json.dumps({"SPAirPortDataType": [{"spairport_airport_interfaces": [{
    "spairport_current_network_information": {
        "_name": "HomeNet", "spairport_network_channel": "149 (5GHz, 80MHz)",
        "spairport_signal_noise": "-55 dBm / -92 dBm",
        "spairport_security_mode": "spairport_security_mode_wpa3_personal"},
    "spairport_airport_other_local_wireless_networks": [
        {"_name": "Neighbor", "spairport_network_channel": "1 (2GHz, 20MHz)",
         "spairport_signal_noise": "-80 dBm / -92 dBm",
         "spairport_security_mode": "spairport_security_mode_none"}],
}]}]})


class ParserTests(unittest.TestCase):
    def test_nmcli(self):
        nets = parse_nmcli(NMCLI)
        self.assertEqual(len(nets), 3)
        self.assertTrue(nets[0].connected)
        self.assertEqual(nets[0].bssid, "AA:BB:CC:DD:EE:01")
        self.assertEqual(nets[1].ssid, "Cafe:Guest")
        self.assertEqual(nets[1].security, "Open")
        self.assertEqual(nets[1].band, "5 GHz")
        self.assertEqual(nets[2].ssid, "(hidden)")

    def test_netsh(self):
        nets = parse_netsh(NETSH, NETSH_IFACE)
        self.assertEqual([n.channel for n in nets], [6, 44, 1])
        self.assertTrue(nets[0].connected)
        self.assertFalse(nets[1].connected)
        self.assertEqual(nets[1].band, "5 GHz")
        self.assertEqual(nets[2].security, "Open")

    def test_system_profiler(self):
        nets = parse_system_profiler(MAC)
        self.assertEqual(len(nets), 2)
        cur = nets[0]
        self.assertTrue(cur.connected)
        self.assertEqual(cur.channel, 149)
        self.assertEqual(cur.signal, 90)
        self.assertIn("WPA3", cur.security)
        self.assertEqual(nets[1].security, "Open")

    def test_ping_times(self):
        out = "64 bytes: time=12.5 ms\n64 bytes: time=10 ms\nReply: time<1ms\n"
        self.assertEqual(parse_ping_times(out), [12.5, 10.0, 0.5])


class AnalysisTests(unittest.TestCase):
    def net(self, ch, sig=80, **kw):
        from wifi_enhancer.scanner import channel_to_freq
        return Network(ssid=kw.get("ssid", f"n{ch}"), bssid="x", signal=sig, channel=ch,
                       frequency=channel_to_freq(ch), security=kw.get("sec", "WPA2"),
                       connected=kw.get("connected", False))

    def test_overlap(self):
        c = congestion_24([self.net(6)])
        self.assertGreater(c[6], c[4])
        self.assertGreater(c[4], 0)
        self.assertEqual(c[1], 0)
        self.assertEqual(c[11], 0)

    def test_recommends_quiet_channel(self):
        nets = [self.net(6, connected=True, ssid="me")] + [self.net(6, 70) for _ in range(4)] + [self.net(1, 60)]
        a = analyze(nets)
        self.assertEqual(a["best_channel"]["2.4 GHz"], 11)
        self.assertTrue(any("channel 11" in t["title"] for t in a["tips"]))

    def test_security_and_weak_signal(self):
        a = analyze([self.net(1, 25, sec="Open", connected=True)])
        titles = [t["title"] for t in a["tips"]]
        self.assertIn("Weak signal", titles)
        self.assertIn("Unencrypted network", titles)
        self.assertEqual(a["quality"], "Weak")

    def test_demo_runs(self):
        a = analyze(demo_networks(seed=1))
        self.assertIsNotNone(a["current"])
        self.assertTrue(a["tips"])


if __name__ == "__main__":
    unittest.main()
