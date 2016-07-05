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
import logging.handlers
import shlex
import sys
import time
import signal
import re
import inspect
import libxml2
import libvirt
import os

from quantum.plugins.neuca.agent import ovs_network as ovs  

from optparse import OptionParser
from sqlalchemy.ext.sqlsoup import SqlSoup
from subprocess import *


# Global constants.
OP_STATUS_UP = "UP"
OP_STATUS_DOWN = "DOWN"

# A placeholder for dead vlans.
DEAD_VLAN_TAG = "4095"

REFRESH_INTERVAL = 2


# A class to represent a VIF (i.e., a port that has 'iface-id' and 'vif-mac'
# attributes set).
class NEUCAPort:
    @classmethod
    def set_root_helper(self, rh):
        self.root_helper = rh
    
    def __init__(self, port_name, vif_iface, vif_mac, bridge, ID, vm_ID):
        self.port_name = port_name
        self.vif_iface = vif_iface
        self.vif_mac = vif_mac
        self.bridge = bridge
        self.ID = ID
        self.vm_ID = vm_ID

    def __str__(self):
        if self.bridge:
            bridge_name = self.bridge.getName()
        else:
            bridge_name = None
        
        return "port_name: "  + str(self.port_name) + \
               ", vif_iface: "  + str(self.vif_iface) + \
               ", vif_mac: "    + str(self.vif_mac) + \
               ", bridge: "     + str(bridge_name) + \
               ", ID: "         + str(self.ID) + \
               ", vm_ID: "         + str(self.vm_ID) 

    @classmethod
    def run_cmd(self, args):
        cmd = shlex.split(self.root_helper) + args

        if not cmd:
            return 'No Command'
        
        LOG.debug("Running command: " + " ".join(cmd))
        p = Popen(cmd, stdout=PIPE)
        retval = p.communicate()[0]
        if p.returncode == -(signal.SIGALRM):
            LOG.debug("Timeout running command: " + " ".join(cmd))
        return (p.returncode, retval)

    def destroy(self):
        LOG.info("Destroying port: " + self.port_name + ", vif_iface: " + self.vif_iface  + ", vm_ID: " + str(self.vm_ID))

        vm_exists = True
        conn = None
        if self.vm_ID:
            try:
                conn = libvirt.open("qemu:///system")
                if not conn:
                    LOG.info('Failed to open connection to the libvirt hypervisor')
                    return
                
                dom = conn.lookupByName(self.vm_ID)
                if not dom:
                    LOG.info('Failed to find dom ' + self.vm_ID  + ' when querying the libvirt hypervisor')
                    return

            except:
                vm_exists = False
                LOG.debug('libvirt failed to find ' + self.vm_ID )

            deviceXML = "<interface type='bridge'> <source bridge='" + self.bridge.getName() + "'/> <mac address='" + self.vif_mac + "'/> <virtualport type='openvswitch'> </virtualport> <model type='virtio' /> <driver name='vhost' txmode='iothread' ioeventfd='on'/> </interface>"

            LOG.info("Delete interface: " + self.vif_mac + ", "+ self.vif_iface)
            try:
                if vm_exists:
                    dom.detachDeviceFlags(deviceXML, libvirt.VIR_DOMAIN_AFFECT_CURRENT)
            except:
                LOG.exception('libvirt failed to detach iface ' + self.port_name + ' from ' + self.vm_ID )
 
            if conn:
                conn.close()

    def create(self):
        LOG.info("Creating Port: " + str(self))

        if self.vm_ID:
            conn = None
            try:
                #add device to vm
                conn = libvirt.open("qemu:///system")
                if not conn:
                    LOG.error('Failed to open connection to the libvirt hypervisor')
                    return

                dom = conn.lookupByName(self.vm_ID)
                if not dom:
                    LOG.debug('Failed to find dom ' + self.vm_ID  + ' when querying the libvirt hypervisor')
                    return
            except:
                LOG.debug('libvirt failed to find ' + self.vm_ID )
                return

            deviceXML = "<interface type='bridge'> <source bridge='" + self.bridge.getName() + "'/> <mac address='" + self.vif_mac + "'/> <virtualport type='openvswitch'> <parameters interfaceid='" + self.ID + "'/> </virtualport> <model type='virtio' /> <target dev='" + self.vif_iface + "'/> <driver name='vhost' txmode='iothread' ioeventfd='on'/> </interface>"

            LOG.info("Creating interface: " + self.vif_mac + ", "+ self.vif_iface )
            try:
                dom.attachDeviceFlags(deviceXML, libvirt.VIR_DOMAIN_AFFECT_CURRENT)
                self.run_cmd(["ifconfig", self.vif_iface, "up" ])
            except:
                LOG.exception('libvirt failed to add iface to ' + self.vm_ID )

            if conn:
                conn.close() 
            self.update()

    def update(self):
        if(self.bridge.ingress_policing_rate != None):
            LOG.info("set_port_ingress_rate: " + str(self.vif_iface) + " to " +  str(self.bridge.ingress_policing_rate))
            ovs.OVS_Network.set_port_ingress_rate(self.vif_iface, self.bridge.ingress_policing_rate)

        if(self.bridge.ingress_policing_burst !=None):
            LOG.info("set_port_ingress_burst: " + str(self.vif_iface) + " to " + str(self.bridge.ingress_policing_burst))
            ovs.OVS_Network.set_port_ingress_burst(self.vif_iface, self.bridge.ingress_policing_burst)

    def init_interfaces(self, interfaces):
        self.interfaces = interfaces


class NEUCABridge:
    @classmethod
    def set_root_helper(self, rh):
        self.root_helper = rh
 
    @classmethod
    def run_cmd(self, args):
        cmd = shlex.split(self.root_helper) + args

        if not cmd:
            return 'No Command'


        LOG.debug("Running command: " + " ".join(cmd))
        p = Popen(cmd, stdout=PIPE)
        retval = p.communicate()[0]
        if p.returncode == -(signal.SIGALRM):
            LOG.debug("Timeout running command: " + " ".join(cmd))
        return (p.returncode, retval)

    @classmethod
    def getMac(self, port_name):
        raw = self.run_cmd(["ifconfig", port_name])
        try:
            mac = raw.split(' ')[5]
        except:
            mac = 'mac_error'
        
        if not re.match( r'^[0-9a-fA-f][0-9a-fA-f]:[0-9a-fA-f][0-9a-fA-f]:[0-9a-fA-f][0-9a-fA-f]:[0-9a-fA-f][0-9a-fA-f]:[0-9a-fA-f][0-9a-fA-f]:[0-9a-fA-f][0-9a-fA-f]$', mac, re.I):
            mac='mac_error'

        return mac

    @classmethod
    def getMac_libvirt(self, vif_name):
        found = False

        conn = libvirt.open("qemu:///system")

        try:
            for dom_id in conn.listDomainsID():
                d = conn.lookupByID(dom_id)

                text = d.XMLDesc(0)
                doc = libxml2.parseDoc(text)
                ctxt =  doc.xpathNewContext()
                result = ctxt.xpathEval('//domain/devices/interface')

                for node in result:
                    name = node.xpathEval('target')[0].prop('dev')
                    mac = node.xpathEval('mac')[0].prop('address')

                    if name == vif_name:
                        rtn_val = str(mac)
                        found = True
                        break

                doc.freeDoc()
                ctxt.xpathFreeContext()
        except:
            LOG.exception("getMac_libvirt error for vif_name = " + str(vif_name))

        if not found:
            rtn_val = "not found"

        if conn:
            conn.close()
        return rtn_val

    def getName(self):
        return self.br_name

    def add_port(self, port):
        self.ports[port.port_name] = port

    def __init__(self, name, switch_name, vlan_tag, switch_iface, ingress_policing_rate, ingress_policing_burst):
        self.br_name = name
        self.switch_name = switch_name
        self.vlan_tag = vlan_tag 
        self.switch_iface = switch_iface
        self.vlan_iface = None 
        self.ingress_policing_rate = ingress_policing_rate
        self.ingress_policing_burst = ingress_policing_burst
    
        if self.vlan_tag != None and self.switch_iface != None:
            self.vlan_iface = self.switch_iface + "." + str(self.vlan_tag)

        self.ports = {}

    def __str__(self):
        return "br_name = "    + str(self.br_name) + \
               ", switch_name = "    + str(self.switch_name) + \
               ", vlan_tag = " + str(self.vlan_tag) + \
               ", switch_if = "  + str(self.switch_iface) + \
               ", vlan_iface = "  + str(self.vlan_iface) + \
               ", ingress_policing_rate = " + str(self.ingress_policing_rate) + \
               ", ingress_policing_burst = "  + str(self.ingress_policing_burst)

    # Really destroys Bridge and all ports on system
    def destroy(self):
        LOG.info("Destroying bridge: " + str(self.br_name))
 
        #delete all ports
        for port in self.ports.values():
            port.destroy()
 
        #detach and delete vlan iface
        if self.vlan_iface:
            LOG.info("Deleting VLAN interface: " + str(self.vlan_iface))
            ovs.OVS_Network.delete_port(self.br_name, self.vlan_iface)
            self.run_cmd(["ifconfig", self.vlan_iface, "down"])
            self.run_cmd(["vconfig", "rem", self.vlan_iface])

        #delete bridge
        ovs.OVS_Network.delete_bridge(self.br_name)

    # Really creates the Bridge on the system
    def create(self):
        LOG.info("Create bridge: " + str(self.br_name))
        
        #create vlan_if 
        self.run_cmd(["vconfig", "add", self.switch_iface, str(self.vlan_tag)])
        
        #LOG.debug("ifconfig " + self.switch_iface + '.' +  str(self.vlan_tag) + ' up')
        (exitcode, retval) = self.run_cmd(["ifconfig", self.switch_iface + '.' +  str(self.vlan_tag), 'up'])
        if exitcode != 0:
            LOG.error("Failed to bring up " + self.switch_iface + '.' +  str(self.vlan_tag) + \
                      " ; Please ensure that " + self.switch_iface + \
                      " is the correct interface name, and has been brought up.")
 
        #create the bridge in ovs
        ovs.OVS_Network.reset_bridge(self.br_name.strip('"'))
        
        self.run_cmd(["ifconfig", self.br_name.strip('"'), 'up'])

        #add the vlan iface 
        ovs.OVS_Network.add_port(self.br_name, self.vlan_iface)
        

class NEUCAQuantumAgent(object):
    def __init__(self, config_file):
        global config
        self.config_file = config_file

        #parse ini config file
        config = ConfigParser.ConfigParser()
        try:
            config.read(self.config_file)
        except Exception, e:
            LOG.error("Unable to parse config file \"%s\": %s"
                      % (self.config_file, str(e)))
            raise e

        # Get common parameters.
        try:
            integ_br = config.get("NEUCA", "integration-bridge")
            if not len(integ_br):
                raise Exception('Empty integration-bridge in configuration file.')

            db_connection_url = config.get("DATABASE", "sql_connection")
            if not len(db_connection_url):
                raise Exception('Empty db_connection_url in configuration file.')

            self.root_helper = config.get("AGENT", "root_helper")
            
            isVerbose = config.get("NEUCA", "verbose")
            if isVerbose.lower() == 'true':
                isVerbose = True
            else:
                isVerbose = False

            log_dir = config.get("NEUCA", "log_dir")

        except Exception, e:
            LOG.error("Error parsing common params in config_file: '%s': %s"
                      % (config_file, str(e)))
            sys.exit(1)

        #configure logging                                                                                                                         
        if isVerbose:
            LOG.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s', level=LOG.DEBUG, filename='/dev/null')
        else:
            LOG.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s', level=LOG.WARN, filename='/dev/null')

        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        handler = LOG.handlers.RotatingFileHandler(log_dir + "/neuca-agent.log", backupCount=50, maxBytes=5000000)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        LOG.getLogger('').addHandler(handler)

        LOG.info("Logging Started")

        options = {"sql_connection": db_connection_url}
        self.db = SqlSoup(options["sql_connection"])
        LOG.info("Connecting to database \"%s\" on %s" %
                 (self.db.engine.url.database, self.db.engine.url.host))


        ovs.OVS_Network.set_root_helper(self.root_helper)
        NEUCABridge.set_root_helper(self.root_helper)
        NEUCAPort.set_root_helper(self.root_helper)

    @classmethod
    def __read_interface_info_from_libvirt(self):
        self.iface_to_vm_dict = {}
        
        conn = libvirt.open("qemu:///system")
        
        if not conn:
            LOG.error('Failed to open connection to the libvirt hypervisor')
            return 

        try:
            for dom_id in conn.listDomainsID():
            
                d = conn.lookupByID(dom_id)
                
                text = d.XMLDesc(0)

                doc = libxml2.parseDoc(text)
                ctxt =  doc.xpathNewContext()
                result = ctxt.xpathEval('//domain/devices/interface/target')

                for node in result:
                    self.iface_to_vm_dict[str(node.prop("dev"))] = d.name()

                doc.freeDoc()
                ctxt.xpathFreeContext()

        except:
            LOG.debug('Failed to find domains in libvirt')

        if conn:
            conn.close()

    @classmethod
    def __read_bridge_info_from_ovs(self):

        self.__read_interface_info_from_libvirt()
        
        output = ovs.OVS_Network.run_vsctl(['show'])

        isFirst = True
        rtn_bridges = {}
        lines = output.splitlines()
        for item in lines:
            item = item.strip(' ')

            if item.startswith('Bridge'):
                if not isFirst:
                    curr_br = NEUCABridge(curr_br_name, curr_br_switch_name, curr_br_vlan,
                                          curr_br_vlan_iface, curr_br_rate, curr_br_burst)
                    for p in curr_br_ports:
                        curr_br.add_port(NEUCAPort(p['name'],p['iface'],p['mac'],curr_br,p['ID'],p['curr_port_vm_ID']))
                    rtn_bridges[curr_br_name] = curr_br
                    
                isFirst = False

                curr_br_name = item.split(' ')[1].strip('"')
                curr_br_switch_name = ''
                curr_br_vlan = ''
                curr_br_vlan_iface =''
                curr_br_ports = []
                #TODO
                curr_br_rate = None
                curr_br_burst = None

            if item.startswith('Port'):
                curr_port_name = item.split(' ')[1].strip('"')
                curr_port_iface = curr_port_name
                #curr_port_mac = NEUCABridge.getMac(curr_port_iface).strip('"')
                curr_port_mac = NEUCABridge.getMac_libvirt(curr_port_iface).strip('"')
                curr_port_ID = '' #TODO: should be DB lookup that might fail if port was deleted

                try:
                    curr_port_vm_ID = self.iface_to_vm_dict[curr_port_iface] 
                except:
                    curr_port_vm_ID = None
                #curr_port_vm_internal_iface = None 
                

                #try to classify ports: for now "vif-X" is vif, vlans are found in /proc/net/vlan,
                #everything else is unknown 
                if re.match( r'^vif-[0-9a-fA-f\-]*$', curr_port_name, re.I):
                    #We have a vif                                                                               
                    curr_br_ports.append({ 'name':curr_port_name, 'iface':curr_port_iface, 'mac':curr_port_mac, 
                                           'ID':curr_port_ID, 'curr_port_vm_ID':curr_port_vm_ID }) 
                else:
                    vlan_ifaces = [(f) for f in os.listdir('/proc/net/vlan')]
                    if curr_port_name in vlan_ifaces:
                        #We have a vlan interface 
                        curr_br_vlan = curr_port_name.split('.')[1].strip('"')
                        curr_br_vlan_iface = curr_port_name.split('.')[0].strip('"')
                        curr_br_switch_name = '' #TODO: should be reverse conf file lookup
                    else:
                        #We don't know what we have
                        pass

        if not isFirst:
            curr_br = NEUCABridge(curr_br_name, curr_br_switch_name, curr_br_vlan, curr_br_vlan_iface, curr_br_rate, curr_br_burst)
            for p in curr_br_ports:
                curr_br.add_port(NEUCAPort(p['name'],p['iface'],p['mac'],curr_br,p['ID'],p['curr_port_vm_ID']))
            rtn_bridges[curr_br_name] = curr_br

        return rtn_bridges

    @classmethod
    def __read_bridge_info_from_db_old(self, db):
        rtn_bridges = {}
        
        net_join = db.join(db.networks, db.network_properties, db.network_properties.network_id==db.networks.uuid)
        port_join = db.with_labels(db.join(db.ports, db.port_properties, db.port_properties.port_id==db.ports.uuid))
        all_join = db.join(port_join, net_join, port_join.ports_network_id==net_join.uuid)

        #get networks
        try:
            all_nets = net_join.all()
        except:
            all_nets = []
    
        for net in all_nets:
            try:
                if net.tenant_id == config.get("NEUCA", 'neuca_tenant_id'):
                    curr_br_name_long = net.name
                    curr_br_name = 'br-'+ config.get("NETWORKS", net.switch_name) +"-"+str(net.vlan_tag)
                    curr_br_switch_name = net.switch_name
                    curr_br_vlan = str(net.vlan_tag)
                    curr_br_vlan_iface = config.get("NETWORKS", net.switch_name) # + "." + str(net.vlan_tag)
                    curr_br_ports = []
                    curr_br_rate = net.max_ingress_rate
                    curr_br_burst = net.max_ingress_burst
 
                    curr_br = NEUCABridge(curr_br_name, curr_br_switch_name, curr_br_vlan,
                                          curr_br_vlan_iface, curr_br_rate, curr_br_burst)
                    for p in all_join.filter_by(name=curr_br_name_long).all():   #where net name = curr_br_switch_name
                        port_name = 'vif-' + p.ports_uuid[-11:]
                        curr_br.add_port(NEUCAPort(port_name, port_name, p.port_properties_mac_addr,
                                                   curr_br, p.port_properties_port_id, p.port_properties_vm_id))
                        rtn_bridges[curr_br_name] = curr_br
            except:
                LOG.debug('Skipping unknown network ' + net.switch_name)
                pass    
            
        return rtn_bridges

    @classmethod
    def __read_bridge_info_from_db(self, db):

        conn = None
        instances = []

        # First, get the list of defined, but not running, instances.
        try:
           conn = libvirt.open("qemu:///system")
           instances = conn.listDefinedDomains()
           if not conn:
               LOG.error('Failed to open connection to the libvirt hypervisor')
               return
        except:
           LOG.debug('Unable to open libvirt connection.')
           return
        
        # Now, get the list of running instances, and append.
        ids = conn.listDomainsID()
        for id in ids:
           try:
              dom = conn.lookupByID(id)
              if dom:
                  new_instance_name = dom.name()
                  LOG.debug(new_instance_name)
                  instances.append(new_instance_name)
           except:
              LOG.debug('libvirt failed to find vm ' + id )


        #instances=['instance-00000f1c','instance-00000f1d']
   
        LOG.debug( 'instances: ' + str(instances) )

        rtn_bridges = {}

        net_join = db.join(db.networks, db.network_properties, db.network_properties.network_id==db.networks.uuid)
        port_join = db.with_labels(db.join(db.ports, db.port_properties, db.port_properties.port_id==db.ports.uuid))
        all_join = db.join(port_join, net_join, port_join.ports_network_id==net_join.uuid)

        #ports_interface_id='instance-00000f1b.fe:16:3e:00:68:eb'
        all_ports=[]
        for inst in instances:
            all_ports += all_join.filter_by(port_properties_vm_id=inst).all()
        LOG.debug(str(all_ports))
 
        try: 
            neuca_tenant_id=config.get("NEUCA", 'neuca_tenant_id')
        except:
            LOG.debug('Unspecified NEuca Tenant ID, check neuca quantum config file')

        for port in all_ports:
            try:
                if port.tenant_id == neuca_tenant_id:
                     curr_br_name = 'br-'+ config.get("NETWORKS", port.switch_name) +"-"+str(port.vlan_tag)
                     if curr_br_name in rtn_bridges:
                         curr_br = rtn_bridges[curr_br_name]       
                     else:
                         curr_br_name_long = port.name
                         curr_br_name = 'br-'+ config.get("NETWORKS", port.switch_name) +"-"+str(port.vlan_tag)
                         curr_br_switch_name = port.switch_name
                         curr_br_vlan = str(port.vlan_tag)
                         curr_br_vlan_iface = config.get("NETWORKS", port.switch_name) # + "." + str(net.vlan_tag)
                         curr_br_ports = []
                         curr_br_rate = port.max_ingress_rate
                         curr_br_burst = port.max_ingress_burst

                         curr_br = NEUCABridge(curr_br_name, curr_br_switch_name, curr_br_vlan,
                                               curr_br_vlan_iface, curr_br_rate, curr_br_burst)
                         rtn_bridges[curr_br_name] = curr_br
	                 
                port_name = 'vif-' + port.ports_uuid[-11:]
                curr_br.add_port(NEUCAPort(port_name, port_name, port.port_properties_mac_addr,
                                           curr_br, port.port_properties_port_id, port.port_properties_vm_id))
            except:
                LOG.debug('Error adding port ' + str(port.ports_interface_id))

        if conn:
            conn.close()
        return rtn_bridges

    def print_bridges(self, bridges):
        LOG.info('######################################')
        for br in bridges.values():
            LOG.info('Bridge: ' + str(br))
            for port in br.ports.values():
                LOG.info('\tPort: ' + str(port))
        LOG.info('######################################')

    def update_bridges(self, old_bridges, new_bridges):
        br_int = config.get("NEUCA", 'integration-bridge')

        #delete old bridges and ports that are not in the new_bridge
        for br_old in old_bridges.keys():
            if br_old == br_int:
                LOG.debug("Skipping: " + br_old)
                continue

            if not br_old in new_bridges:
                LOG.info("Deleting old bridge: " + br_old)
                old_bridges[br_old].destroy()
            else:
                for port_old in old_bridges[br_old].ports:
                    new_bridge_entry = new_bridges.get(br_old)
                    if not new_bridge_entry:
                        continue
                    if not port_old in new_bridge_entry.ports:
                        LOG.info("Deleting port: " + port_old)
                        old_bridges[br_old].ports[port_old].destroy()
                    else:
                        old_bridges[br_old].ports[port_old].update()

        #add new bridges and ports
        for br_new in new_bridges.keys():
            if br_new == br_int:
                continue

            if not br_new in old_bridges:
                LOG.info("Adding new bridge: " + br_new)
                new_bridges[br_new].create()

            for port_new in new_bridges[br_new].ports:
                old_bridge_entry = old_bridges.get(br_new)
                if not old_bridge_entry:
                    continue
                if not port_new in old_bridge_entry.ports:
                    LOG.info("Adding port to old bridge: " + port_new)
                    new_bridges[br_new].ports[port_new].create()

    def daemon_loop(self):
        while True:
            try:
                #Get the current state of local bridges/ports/interfaces
                old_bridges = self.__read_bridge_info_from_ovs()
                #self.print_bridges(old_bridges)
            
                #Get the desired state of local bridges/ports/interfaces from db
                new_bridges = self.__read_bridge_info_from_db(self.db)
                #self.print_bridges(new_bridges)
            
                #Apply changes
                self.update_bridges(old_bridges, new_bridges)

            except KeyboardInterrupt:
                LOG.error("Exception: KeyboardInterrupt")
                sys.exit(0)
            except:
                LOG.exception("Exception in daemon_loop!")

            try:
               self.db.commit()
            except Exception as e:
               self.db.rollback()
            
            time.sleep(REFRESH_INTERVAL)


import time
from daemon import runner

class NEucaAgentd():
    def __init__(self, config_file):
        self.stdin_path = '/dev/null'
        self.stdout_path = '/dev/null'
        self.stderr_path = '/dev/null'
        self.pidfile_path =  '/var/run/neuca-agentd.pid'
        self.pidfile_timeout = 10

        self.config_file = config_file

    def run(self):
        self.plugin = NEUCAQuantumAgent(self.config_file)
        self.plugin.daemon_loop()


def main():
    from optparse import OptionParser

    usagestr = "%prog [OPTIONS] <config file>"
    parser = OptionParser(usage=usagestr)
    parser.add_option("-d", "--daemonize", dest="daemonize",
      action="store_true", default=False, help="Daemonize the NEuca Agent")
   
    options, args = parser.parse_args()

    if len(args) != 1:
        parser.print_help()
        sys.exit(1)

    #Stop a running daemon
    if args[0] == 'stop':
        sys.argv=[sys.argv[0], 'stop']

        app = NEucaAgentd(None)
        daemon_runner = runner.DaemonRunner(app)
        daemon_runner.do_action()
        sys.exit(0)

    #Start an agent
    config_file = args[0]
    
    if options.daemonize:
        #start as daemon
        #Re-create argv without options for daemonizing code
        sys.argv=[sys.argv[0], 'start']

        app = NEucaAgentd(config_file)
        daemon_runner = runner.DaemonRunner(app)
        daemon_runner.do_action()
    else:
        #start in terminal
        plugin = NEUCAQuantumAgent(config_file)
        plugin.daemon_loop()

    sys.exit(0)

if __name__ == "__main__":
    main()
