# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright (c) 2012 Renaissance Computing Institute except where noted. All rights reserved.
#
# This software is distributed under the terms of the Eclipse Public License
# Version 1.0 found in the file named LICENSE.Eclipse, which was shipped with
# this distribution. Any use, reproduction or distribution of this software
# constitutes the recipient's acceptance of the Eclipse license terms. This
# notice and the full text of the license must be included with any distribution
# of this software.
#
# Renaissance Computing Institute,
# (A Joint Institute between the University of North Carolina at Chapel Hill,
# North Carolina State University, and Duke University)
# http://www.renci.org
#
# For questions, comments please contact software@renci.org
#
# @author: Paul Ruth, RENCI - UNC Chapel Hill
#
# Credit to the following authors, from whose work this was derived:
# @author: Somik Behera, Nicira Networks, Inc.
# @author: Brad Hall, Nicira Networks, Inc.
# @author: Dan Wendlandt, Nicira Networks, Inc.
# @author: Dave Lapsley, Nicira Networks, Inc.

import ConfigParser
import logging as LOG
from optparse import OptionParser
import os
import sys

from quantum.api.api_common import OperationalStatus
from quantum.common import exceptions as q_exc
from quantum.common.config import find_config_file
from quantum.quantum_plugin_base import QuantumPluginBase

import quantum.common.utils
import quantum.db.api as db
import neuca_db
import nova.db.api as nova_db

CONF_FILE = find_config_file(
  {"plugin": "neuca"},
  None, "neuca_quantum_plugin.ini")

LOG.basicConfig(level=LOG.WARN)
LOG.getLogger("neuca_quantum_plugin")


# Exception thrown if no more VLANs are available
class NoFreeVLANException(Exception):
    pass


class VlanMap(object):
    vlans = {}
    net_ids = {}
    free_vlans = set()
    VLAN_MIN = 1
    VLAN_MAX = 4094

    def __init__(self):
        self.vlans.clear()
        self.net_ids.clear()
        self.free_vlans = set(xrange(self.VLAN_MIN, self.VLAN_MAX + 1))

    def already_used(self, vlan_id, network_id):
        self.free_vlans.remove(vlan_id)
        self.set_vlan(vlan_id, network_id)

    def set_vlan(self, vlan_id, network_id):
        self.vlans[vlan_id] = network_id
        self.net_ids[network_id] = vlan_id

    def acquire(self, network_id):
        if len(self.free_vlans):
            vlan = self.free_vlans.pop()
            self.set_vlan(vlan, network_id)
            LOG.debug("Allocated VLAN %s for network %s" % (vlan, network_id))
            return vlan
        else:
            raise NoFreeVLANException("No VLAN free for network %s" %
                                      network_id)

    def release(self, network_id):
        vlan = self.net_ids.get(network_id, None)
        if vlan is not None:
            self.free_vlans.add(vlan)
            del self.vlans[vlan]
            del self.net_ids[network_id]
            LOG.debug("Deallocated VLAN %s (used by network %s)"
                      % (vlan, network_id))
        else:
            LOG.error("No vlan found with network \"%s\"", network_id)


class NEUCAQuantumPlugin(QuantumPluginBase):


    def __init__(self, configfile=None):
        LOG.info("Initializing NEUCAQuantumPlugin")
        self.config = ConfigParser.ConfigParser()
        if configfile is None:
            if os.path.exists(CONF_FILE):
                configfile = CONF_FILE
            else:
                configfile = find_config(os.path.abspath(
                        os.path.dirname(__file__)))
        if configfile is None:
            raise Exception("Configuration file \"%s\" doesn't exist" %
              (configfile))
        LOG.debug("Using configuration file: %s" % configfile)
        self.config.read(configfile)
        LOG.debug("Config: %s" % self.config)

        options = {"sql_connection": self.config.get("DATABASE", "sql_connection")}
        db.configure_db(options)

    def get_all_networks(self, tenant_id, **kwargs):
        nets = []
        for x in db.network_list(tenant_id):
            LOG.debug("Adding network: %s" % x.uuid)
            nets.append(self._make_net_dict(str(x.uuid), x.name,
                                            None, x.op_status))
        return nets

    def _make_net_dict(self, net_id, net_name, ports, op_status):
        res = {'net-id': net_id,
                'net-name': net_name,
                'net-op-status': op_status}
        if ports:
            res['net-ports'] = ports
        return res

    def create_network(self, tenant_id, net_name, **kwargs):
        net = db.network_create(tenant_id, net_name,
                          op_status=OperationalStatus.UP)
        LOG.debug("Created network: %s" % net)
        LOG.debug("PRUTH: Created network: %s %s" % (net, net_name))
 
        properties = net_name.split(':')

        LOG.debug("PRUTH: len(properties) = %d" % (len(properties)))
        if len(properties) >= 3 and tenant_id == self.config.get("NEUCA", "neuca_tenant_id"):
            #  network_type:switch_name:vlan_tag[:max_ingress_rate][:max_ingress_burst]
            network_type = properties[0] 
            switch_name = properties[1]
            vlan_tag = properties[2]
            
            if len(properties) >= 4:
                max_ingress_rate =  properties[3]
            else:
                max_ingress_rate = 0

            if len(properties) >= 5:
                max_ingress_burst = properties[4]
            else:
                max_ingress_burst = 0
        else:
            LOG.debug("PRUTH: not enough properties or not neuca: len(properties) = %d, %s" % (len(properties),net_name))
        
            network_type = 'management'
            switch_name = 'management'
            vlan_tag = 0  #should be managment vlan from conf file
            max_ingress_rate =  0
            max_ingress_burst = 0

            

        neuca_db.add_network_properties(str(net.uuid), network_type, switch_name, vlan_tag, max_ingress_rate, max_ingress_burst) 
        return self._make_net_dict(str(net.uuid), net.name, [],
                                        net.op_status)

    def delete_network(self, tenant_id, net_id):
        db.validate_network_ownership(tenant_id, net_id)
        net = db.network_get(net_id)

        # Verify that no attachments are plugged into the network
        for port in db.port_list(net_id):
            if port.interface_id:
                raise q_exc.NetworkInUse(net_id=net_id)
        net = db.network_destroy(net_id)
        neuca_db.remove_network_properties(net_id)
        return self._make_net_dict(str(net.uuid), net.name, [],
                                        net.op_status)

    def get_network_details(self, tenant_id, net_id):
        db.validate_network_ownership(tenant_id, net_id)
        net = db.network_get(net_id)
        ports = self.get_all_ports(tenant_id, net_id)
        return self._make_net_dict(str(net.uuid), net.name,
                                    ports, net.op_status)

    def update_network(self, tenant_id, net_id, **kwargs):
        db.validate_network_ownership(tenant_id, net_id)
        net = db.network_update(net_id, tenant_id, **kwargs)

        #LOG.debug("PRUTH: update_network: %s %s" % (net, kwargs['name']))
        update_network_properties(net.network_id, net.network_type, net.switch_name, net.vlan_tag, net.max_ingress_rate, net.max_ingress_burst)

        return self._make_net_dict(str(net.uuid), net.name,
                                        None, net.op_status)

    def _make_port_dict(self, port):
        if port.state == "ACTIVE":
            op_status = port.op_status
        else:
            op_status = OperationalStatus.DOWN

        return {'port-id': str(port.uuid),
                'port-state': port.state,
                'port-op-status': op_status,
                'net-id': port.network_id,
                'attachment': port.interface_id}

    def get_all_ports(self, tenant_id, net_id, **kwargs):
        ids = []
        db.validate_network_ownership(tenant_id, net_id)
        ports = db.port_list(net_id)
        # This plugin does not perform filtering at the moment
        return [{'port-id': str(p.uuid)} for p in ports]

    def create_port(self, tenant_id, net_id, port_state=None, **kwargs):
        LOG.debug("PRUTH: Creating port with network_id: %s" % net_id)

        neuca_tenant_id = self.config.get("NEUCA", "neuca_tenant_id")
        
        if tenant_id != neuca_tenant_id:
            db.validate_network_ownership(tenant_id, net_id)
            #new_mac = None
        #else:
            #new_mac = str(quantum.common.utils.generate_mac())
        #    pass

        port = db.port_create(net_id, port_state,
                                op_status=OperationalStatus.DOWN)
        

        LOG.debug("PRUTH: neuca_tenant_id: %s, net_id: %s, interface_id: %s" % (neuca_tenant_id, net_id, port.interface_id))
        LOG.debug("PRUTH: kwargs:%s" % (str(kwargs)))
        
        neuca_db.add_port_properties(port.uuid,None,None)

        return self._make_port_dict(port)

    def delete_port(self, tenant_id, net_id, port_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        port = db.port_destroy(port_id, net_id)

        #delete from port_properties
        neuca_db.remove_port_properties(port_id)

        return self._make_port_dict(port)

    def update_port(self, tenant_id, net_id, port_id, **kwargs):
        """
        Updates the state of a port on the specified Virtual Network.
        """
        db.validate_port_ownership(tenant_id, net_id, port_id)
        port = db.port_get(port_id, net_id)
        db.port_update(port_id, net_id, **kwargs)
        return self._make_port_dict(port)

    def get_port_details(self, tenant_id, net_id, port_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        port = db.port_get(port_id, net_id)
        return self._make_port_dict(port)

    def plug_interface(self, tenant_id, net_id, port_id, remote_iface_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        db.port_set_attachment(port_id, net_id, remote_iface_id)

        iface_properties = remote_iface_id.split('.')

        LOG.debug("PRUTH: len(iface_properties) = %d" % (len(iface_properties)))
        if len(iface_properties) >= 2 and tenant_id == self.config.get("NEUCA", "neuca_tenant_id"):
            #  vm_id.vm_iface 
            vm_id = iface_properties[0]
            vm_mac = iface_properties[1]
            #vm_mac = str(quantum.common.utils.generate_mac())
        else:
            LOG.debug("PRUTH: not enough iface properites or not neuca: len(iface_properties) = %d, %s" % (len(iface_properties),remote_iface_id))
            vm_id = None
            vm_mac = None

        neuca_db.update_port_properties_iface(port_id, vm_id, vm_mac)

    def unplug_interface(self, tenant_id, net_id, port_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        db.port_set_attachment(port_id, net_id, "")
        db.port_update(port_id, net_id, op_status=OperationalStatus.DOWN)

        #unplug in port_properties
        vm_id = None
        neuca_db.update_port_properties_iface(port_id, vm_id, None)



    def get_interface_details(self, tenant_id, net_id, port_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        res = db.port_get(port_id, net_id)
        return res.interface_id
