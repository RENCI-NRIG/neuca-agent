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

import uuid

from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relation
from quantum.db.models import BASE


class network_properties(BASE):
    """Represents a network's properies including vlan_tag switch max_rate and burst_rate"""
    __tablename__ = 'network_properties'

    network_id = Column(String(255), primary_key=True)
    network_type = Column(String(255))
    switch_name = Column(String(255))
    vlan_tag = Column(Integer)
    max_ingress_rate = Column(Integer)
    max_ingress_burst = Column(Integer)

    def __init__(self, network_id, network_type, switch_name, vlan_tag, max_ingress_rate, max_ingress_burst):
        self.network_id = network_id
        self.network_type = network_type
        self.switch_name = switch_name
        self.vlan_tag = vlan_tag
        self.max_ingress_rate = max_ingress_rate
        self.max_ingress_burst = max_ingress_burst


    def __repr__(self):
        return "<network_properties(%s,%s,%s,%d,%d,%d)>" % \
          (self.network_id, self.network_type, self.switch_name, self.vlan_tag, self.max_ingress_rate, self.max_ingress_burst)



class port_properties(BASE):
    """Represents a port's properies including mac"""
    __tablename__ = 'port_properties'

    port_id = Column(String(255), primary_key=True)
    mac_addr = Column(String(255))
    vm_id = Column(String(255))

    def __init__(self, port_id, mac_addr, vm_id):
        self.port_id = port_id
        self.mac_addr = mac_addr
        self.vm_id = vm_id
     
    def __repr__(self):
        return "<port_properties(%s,%s,%s,%s)>" % \
          (self.port_id, self.mac_addr,self.vm_id)

