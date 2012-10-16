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
#
# #####################################
# 
# Neuca plugin for Quantum.  Based on OVS plugin.
#

from sqlalchemy.orm import exc

import quantum.db.api as db
import quantum.db.models as models
import neuca_models


def get_network_properties():
    session = db.get_session()
    try:
        networks = session.query(neuca_models.network_properties).\
          all()
    except exc.NoResultFound:
        return []
    res = []
    for x in networks:
        res.append((x.network_id, x.network_type, x.switch_name, x.vlan_tag, x.max_ingress_rate, x.max_ingress_burst))
    return res


def add_network_properties(network_id, network_type, switch_name, vlan_tag, max_ingress_rate, max_ingress_burst):
    session = db.get_session()
    network = neuca_models.network_properties(network_id, network_type, switch_name, vlan_tag, max_ingress_rate, max_ingress_burst)
    session.add(network)
    session.flush()
    return network.network_id


def remove_network_properties(netid):
    session = db.get_session()
    try:
        network = session.query(neuca_models.network_properties).\
          filter_by(network_id=netid).\
          one()
        session.delete(network)
    except exc.NoResultFound:
            pass
    session.flush()

def update_network_properties(netid, network_type, switch_name, vlan_tag, max_ingress_rate, max_ingress_burst):
    session = db.get_session()
    try:
        net = session.query(neuca_models.network_properties).\
            filter_by(net_id=netid).\
            one()
    except exc.NoResultFound:
        pass
    
    net.network_type = network_type
    net.switch_name = switch_name
    net.vlan_tag = vlan_tag
    net.max_ingress_rate = max_ingress_rate  
    net.max_ingress_burst = max_ingress_burst

    session.merge(net)
    session.flush()
    return net.net_id



def get_port_properties():
    session = db.get_session()
    try:
        ports = session.query(neuca_models.port_properties).\
          all()
    except exc.NoResultFound:
        return []
    res = []
    for x in ports:
        res.append((x.port_id, x.mac_addr, x.vm_id, x.vm_interface))
    return res

def get_port_properties(portid):
    session = db.get_session()
    try:
        port = session.query(neuca_models.port_properties).\
          filter_by(port_id=portid).\
            one()
    except exc.NoResultFound:
            pass
    return port


def add_port_properties(port_id, mac_addr, vm_id):
    session = db.get_session()
    port = neuca_models.port_properties(port_id, mac_addr, vm_id)
    session.add(port)
    session.flush()
    return port.port_id

def remove_port_properties(portid):
    session = db.get_session()
    try:
        port = session.query(neuca_models.port_properties).\
          filter_by(port_id=portid).\
            one()
        session.delete(port)
    except exc.NoResultFound:
            pass
    session.flush()

 
def update_port_properties_iface(portid, vm_id, vm_mac):
    session = db.get_session()
    try:
        port = session.query(neuca_models.port_properties).\
            filter_by(port_id=portid).\
            one()
    except exc.NoResultFound:
        pass

    port.vm_id = vm_id
    port.mac_addr = vm_mac

    session.merge(port)
    session.flush()
    return port.port_id



