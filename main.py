from kytos.core import KytosEvent, KytosNApp, log
from kytos.core.helpers import listen_to
from pyof.foundation.network_types import ARP, Ethernet, EtherType, IPv4
from pyof.v0x04.common.action import ActionOutput, ActionDLAddr, ActionType, ActionSetField
from pyof.v0x04.common.flow_match import Match
from pyof.v0x04.common.phy_port import Port
from pyof.v0x04.controller2switch.flow_mod import FlowMod, FlowModCommand
from pyof.v0x04.controller2switch.packet_out import PacketOut

from napps.krishna4041.of_l3ls_v2 import settings


class Main(KytosNApp):

    def setup(self):
        pass

    def execute(self):
        pass

    @listen_to('kytos/core.switch.new')
    def create_switch_tables(self, event):
        switch = event.content['switch']
        switch.fw_table = {}
        switch.arp_table = {}

    @listen_to('kytos/of_core.v0x04.messages.in.ofpt_packet_in')
    def handle_packet_in(self, event):
        packet_in = event.content['message']

        ethernet = Ethernet()
        ethernet.unpack(packet_in.data.value)

        in_port = packet_in.in_port.value

        if ethernet.ether_type.value == EtherType.ARP:
            self.handle_arp(ethernet, in_port, event.source)
        elif ethernet.ether_type.value == EtherType.IPV4:
            self.handle_ip(ethernet, in_port, event.source)

    def handle_arp(self, ethernet, in_port, source):
        arp = ARP()
        arp.unpack(ethernet.data.value)

        source.switch.arp_table[arp.spa.value] = arp.sha.value
        source.switch.fw_table[arp.spa.value] = in_port

        log.info('Learning %s at port %d with mac %s.', arp.spa.value, in_port,
                 arp.sha.value)

        if arp.oper.value == 1 and arp.tpa.value in settings.GW_IP:
            reply = ARP(oper=2)
            reply.sha = settings.GW_MAC
            reply.spa = arp.tpa
            reply.tha = arp.sha
            reply.tpa = arp.spa

            frame = Ethernet()
            frame.source = settings.GW_MAC
            frame.destination = ethernet.source
            frame.ether_type = EtherType.ARP
            frame.data = reply.pack()

            packet_out = PacketOut()
            packet_out.data = frame.pack()
            packet_out.actions.append(ActionOutput(port=in_port))

            event_out = KytosEvent(name=('krishna4041/of_l3ls_v2.messages.out.'
                                         'ofpt_packet_out'),
                                   content={'destination': source,
                                            'message': packet_out})

            self.controller.buffers.msg_out.put(event_out)
            log.info('Replygin arp request from %s', arp.spa.value)

    def handle_ip(self, ethernet, in_port, source):
        ipv4 = IPv4()
        ipv4.unpack(ethernet.data.value)

        switch = source.switch

        dest_mac = switch.arp_table.get(ipv4.destination, None)

        log.info('Packet received from %s to %s', ipv4.source,
                 ipv4.destination)

        if dest_mac is not None:
            dest_port = switch.fw_table.get(ipv4.destination)

            flow_mod = FlowMod()
            flow_mod.command = FlowModCommand.OFPFC_ADD
            flow_mod.match = Match()
            flow_mod.match.nw_src = ipv4.source
            flow_mod.match.nw_dst = ipv4.destination
            flow_mod.match.dl_type = EtherType.IPV4
            # flow_mod.actions.append(ActionSetField(action_type=ActionType.OFPAT_SET_DL_SRC,
            #                                      dl_addr=settings.GW_MAC))
            # flow_mod.actions.append(ActionSetField(action_type=ActionType.OFPAT_SET_DL_DST,
            #                                      dl_addr=dest_mac))
            # flow_mod.actions.append(ActionOutput(port=dest_port))

            event_out = KytosEvent(name=('krishna4041.of_l3ls_v2.messages.out.'
                                         'ofpt_flow_mod'),
                                   content={'destination': source,
                                            'message': flow_mod})

            # self.controller.buffers.msg_out.put(event_out)
            log.info('Flow installed! Subsequent packets will be sent directly.')

        else:
            arp_request = ARP(oper=1)
            arp_request.sha = settings.GW_MAC
            arp_request.tpa = ipv4.destination

            frame = Ethernet()
            frame.source = settings.GW_MAC
            frame.destination = 'ff:ff:ff:ff:ff:ff'
            frame.ether_type = EtherType.ARP
            frame.data = arp_request.pack()

            packet_out = PacketOut()
            packet_out.data = frame.pack()
            packet_out.actions.append(ActionOutput(port=Port.OFPP_FLOOD))

            event_out = KytosEvent(name=('krishna4041/of_l3ls_v2.messages.out.'
                                         'ofpt_packet_out'),
                                   content={'destination': source,
                                            'message': packet_out})

            self.controller.buffers.msg_out.put(event_out)
            log.info('ARP request sent to %s', ipv4.destination)

    def shutdown(self):
        pass