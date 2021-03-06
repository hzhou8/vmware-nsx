# Copyright 2014 VMware, Inc.
# All Rights Reserved
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import xml.etree.ElementTree as et

from neutron.i18n import _LE, _LI
from neutron.openstack.common import log as logging
from neutron.openstack.common import loopingcall

WAIT_INTERVAL = 2000
MAX_ATTEMPTS = 5

LOG = logging.getLogger(__name__)


class NsxSecurityGroupUtils(object):

    def __init__(self, nsxv_manager):
        LOG.debug("Start Security Group Utils initialization")
        self.nsxv_manager = nsxv_manager

    def to_xml_string(self, element):
        return et.tostring(element)

    def get_section_with_rules(self, name, rules):
        """Helper method to create section dict with rules."""

        section = et.Element('section')
        section.attrib['name'] = name
        for rule in rules:
            section.append(rule)
        return section

    def get_container(self, nsx_sg_id):
        container = {'type': 'SecurityGroup', 'value': nsx_sg_id}
        return container

    def get_remote_container(self, remote_group_id, remote_ip_mac):
        container = None
        if remote_group_id is not None:
            return self.get_container(remote_group_id)
        if remote_ip_mac is not None:
            container = {'type': 'Ipv4Address', 'value': remote_ip_mac}
        return container

    def get_rule_config(self, applied_to_id, name, action='allow',
                        applied_to='SecurityGroup',
                        source=None, destination=None, services=None,
                        flags=None):
        """Helper method to create a nsx rule dict."""
        ruleTag = et.Element('rule')
        nameTag = et.SubElement(ruleTag, 'name')
        nameTag.text = name
        actionTag = et.SubElement(ruleTag, 'action')
        actionTag.text = action

        apList = et.SubElement(ruleTag, 'appliedToList')
        apTag = et.SubElement(apList, 'appliedTo')
        apTypeTag = et.SubElement(apTag, 'type')
        apTypeTag.text = applied_to
        apValueTag = et.SubElement(apTag, 'value')
        apValueTag.text = applied_to_id

        if source is not None:
            sources = et.SubElement(ruleTag, 'sources')
            sources.attrib['excluded'] = 'false'
            srcTag = et.SubElement(sources, 'source')
            srcTypeTag = et.SubElement(srcTag, 'type')
            srcTypeTag.text = source['type']
            srcValueTag = et.SubElement(srcTag, 'value')
            srcValueTag.text = source['value']

        if destination is not None:
            dests = et.SubElement(ruleTag, 'destinations')
            dests.attrib['excluded'] = 'false'
            destTag = et.SubElement(dests, 'destination')
            destTypeTag = et.SubElement(destTag, 'type')
            destTypeTag.text = destination['type']
            destValueTag = et.SubElement(destTag, 'value')
            destValueTag.text = destination['value']

        if services:
            s = et.SubElement(ruleTag, 'services')
            for protocol, port, icmptype, icmpcode in services:
                svcTag = et.SubElement(s, 'service')
                try:
                    int(protocol)
                    svcProtocolTag = et.SubElement(svcTag, 'protocol')
                    svcProtocolTag.text = str(protocol)
                except ValueError:
                    svcProtocolTag = et.SubElement(svcTag, 'protocolName')
                    svcProtocolTag.text = protocol
                if port is not None:
                    svcPortTag = et.SubElement(svcTag, 'destinationPort')
                    svcPortTag.text = str(port)
                if icmptype is not None:
                    svcPortTag = et.SubElement(svcTag, 'subProtocol')
                    svcPortTag.text = str(icmptype)
                if icmpcode is not None:
                    svcPortTag = et.SubElement(svcTag, 'icmpCode')
                    svcPortTag.text = str(icmpcode)

        if flags:
            if flags.get('ethertype') is not None:
                pktTag = et.SubElement(ruleTag, 'packetType')
                pktTag.text = flags.get('ethertype')
            if flags.get('direction') is not None:
                dirTag = et.SubElement(ruleTag, 'direction')
                dirTag.text = flags.get('direction')
        return ruleTag

    def get_rule_id_pair_from_section(self, resp):
        root = et.fromstring(resp)
        pairs = []
        for rule in root.findall('rule'):
            pair = {'nsx_id': rule.attrib.get('id'),
                    'neutron_id': rule.find('name').text}
            pairs.append(pair)
        return pairs

    def insert_rule_in_section(self, section, nsx_rule):
        section.insert(0, nsx_rule)

    def parse_section(self, xml_string):
        return et.fromstring(xml_string)

    def add_port_to_security_group(self, nsx_sg_id, nsx_vnic_id):
        userdata = {
            'nsx_sg_id': nsx_sg_id,
            'nsx_vnic_id': nsx_vnic_id,
            'attempt': 1
        }
        LOG.info(_LI("Add task to add %(nsx_sg_id)s member to NSX security "
                     "group %(nsx_vnic_id)s"), userdata)
        task = loopingcall.FixedIntervalLoopingCall(
            self._add_security_groups_port_mapping,
            userdata=userdata)
        task.start(WAIT_INTERVAL / 1000)

    def _add_security_groups_port_mapping(self, userdata):
        nsx_vnic_id = userdata.get('nsx_vnic_id')
        nsx_sg_id = userdata.get('nsx_sg_id')
        attempt = userdata.get('attempt')
        LOG.debug("Trying to execute task to add %s to %s attempt %d",
                  nsx_vnic_id, nsx_sg_id, attempt)
        if attempt >= MAX_ATTEMPTS:
            LOG.error(_LE("Stop task to add %(nsx_vnic_id)s to security group "
                          "%(nsx_sg_id)s"), userdata)
            LOG.error(_LE("Exception %s"), userdata.get('exception'))
            raise loopingcall.LoopingCallDone()
        else:
            attempt = attempt + 1
            userdata['attempt'] = attempt

        try:
            h, c = self.nsxv_manager.vcns.add_member_to_security_group(
                nsx_sg_id, nsx_vnic_id)
            LOG.info(_LI("Added %s(nsx_sg_id)s member to NSX security "
                         "group %(nsx_vnic_id)s"), userdata)

        except Exception as e:
            LOG.debug("NSX security group %(nsx_sg_id)s member add "
                      "failed %(nsx_vnic_id)s - attempt %(attempt)d",
                      {'nsx_sg_id': nsx_sg_id,
                       'nsx_vnic_id': nsx_vnic_id,
                       'attempt': attempt})
            userdata['exception'] = e
            LOG.debug("Exception %s", e)
            return

        raise loopingcall.LoopingCallDone()
