#!/usr/bin/env python
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
import shlex
import sys
import time
import signal
import re

from optparse import OptionParser
from sqlalchemy.ext.sqlsoup import SqlSoup
from subprocess import *


# Global constants.
OP_STATUS_UP = "UP"
OP_STATUS_DOWN = "DOWN"

# A placeholder for dead vlans.
DEAD_VLAN_TAG = "4095"

REFRESH_INTERVAL = 2


class OVS_Network:

    @classmethod
    def set_root_helper(self, rh):
        self.root_helper = rh

    @classmethod
    def run_cmd(self, args):
        cmd = shlex.split(self.root_helper) + args
        p = Popen(cmd, stdout=PIPE)
        retval = p.communicate()[0]
        return retval

    @classmethod
    def run_vsctl(self, args):
        full_args = ["ovs-vsctl", "--timeout=2"] + args
        return self.run_cmd(full_args)

    @classmethod
    def delete_bridge(self, br_name):
        self.run_cmd(["ifconfig", br_name, "down" ])
        self.run_vsctl(["del-br", br_name])

    @classmethod
    def reset_bridge(self, br_name):
        self.run_vsctl(["--", "--if-exists", "del-br", br_name])
        self.run_vsctl(["add-br", br_name])

    @classmethod
    def delete_port(self, br_name, port_name):
        self.run_vsctl(["--", "--if-exists", "del-port", br_name,
          port_name])

    @classmethod
    def set_db_attribute(self, table_name, record, column, value):
        args = ["set", table_name, record, "%s=%s" % (column, value)]
        self.run_vsctl(args)

    @classmethod
    def clear_db_attribute(self, table_name, record, column):
        args = ["clear", table_name, record, column]
        self.run_vsctl(args)

    @classmethod
    def run_ofctl(self, br_name, cmd, a1rgs):
        full_args = ["ovs-ofctl", cmd, br_name] + args
        return self.run_cmd(full_args)

    @classmethod
    def remove_all_flows(self):
        self.run_ofctl("del-flows", [])

    @classmethod
    def get_port_ofport(self, port_name):
        return self.db_get_val("Interface", port_name, "ofport")

    @classmethod
    def add_flow(self, **dict):
        if "actions" not in dict:
            raise Exception("must specify one or more actions")
        if "priority" not in dict:
            dict["priority"] = "0"

        flow_str = "priority=%s" % dict["priority"]
        if "match" in dict:
            flow_str += "," + dict["match"]
        flow_str += ",actions=%s" % (dict["actions"])
        self.run_ofctl("add-flow", [flow_str])

    @classmethod
    def delete_flows(self, **dict):
        all_args = []
        if "priority" in dict:
            all_args.append("priority=%s" % dict["priority"])
        if "match" in dict:
            all_args.append(dict["match"])
        if "actions" in dict:
            all_args.append("actions=%s" % (dict["actions"]))
        flow_str = ",".join(all_args)
        self.run_ofctl("del-flows", [flow_str])

    @classmethod
    def add_tunnel_port(self, br_name, port_name, remote_ip):
        self.run_vsctl(["add-port", br_name, port_name])
        self.set_db_attribute("Interface", port_name, "type", "gre")
        self.set_db_attribute("Interface", port_name, "options", "remote_ip=" +
            remote_ip)
        self.set_db_attribute("Interface", port_name, "options", "in_key=flow")
        self.set_db_attribute("Interface", port_name, "options",
            "out_key=flow")
        return self.get_port_ofport(port_name)

    @classmethod
    def add_port(self, br_name, port_name):
        self.run_vsctl(["add-port", br_name, port_name])
        return port_name
    
    @classmethod
    def set_port_ingress_rate(self, iface, rate):
        self.run_vsctl(["set", "Interface", iface, "ingress_policing_rate="+str(rate)])
        return iface

    @classmethod
    def set_port_ingress_burst(self, iface, burst):    
        self.run_vsctl(["set", "Interface", iface, "ingress_policing_burst="+str(burst)])
        return iface

    @classmethod
    def add_patch_port(self, local_name, remote_name):
        self.run_vsctl(["add-port", self.br_name, local_name])
        self.set_db_attribute("Interface", local_name, "type", "patch")
        self.set_db_attribute("Interface", local_name, "options", "peer=" +
                              remote_name)
        return self.get_port_ofport(local_name)

    @classmethod
    def db_get_map(self, table, record, column):
        str = self.run_vsctl(["get", table, record, column]).rstrip("\n\r")
        return self.db_str_to_map(str)

    @classmethod
    def db_get_val(self, table, record, column):
        return self.run_vsctl(["get", table, record, column]).rstrip("\n\r")

    @classmethod
    def db_str_to_map(self, full_str):
        list = full_str.strip("{}").split(", ")
        ret = {}
        for e in list:
            if e.find("=") == -1:
                continue
            arr = e.split("=")
            ret[arr[0]] = arr[1].strip("\"")
        return ret

    @classmethod
    def get_port_name_list(self, br_name):
        res = self.run_vsctl(["list-ports", br_name])
        return res.split("\n")[0:-1]

    @classmethod
    def get_port_stats(self, port_name):
        return self.db_get_map("Interface", port_name, "statistics")

    @classmethod
    def get_xapi_iface_id(self, xs_vif_uuid):
        return self.run_cmd(
                        ["xe",
                        "vif-param-get",
                        "param-name=other-config",
                        "param-key=nicira-iface-id",
                        "uuid=%s" % xs_vif_uuid]).strip()

    @classmethod
    # returns a VIF object for each VIF port
    def get_vif_ports(self):
        edge_ports = []
        port_names = self.get_port_name_list()
        for name in port_names:
            external_ids = self.db_get_map("Interface", name, "external_ids")
            ofport = self.db_get_val("Interface", name, "ofport")
            if "iface-id" in external_ids and "attached-mac" in external_ids:
                p = VifPort(name, ofport, external_ids["iface-id"],
                            external_ids["attached-mac"], self)
                edge_ports.append(p)
            elif "xs-vif-uuid" in external_ids and \
                 "attached-mac" in external_ids:
                # if this is a xenserver and iface-id is not automatically
                # synced to NEUCA from XAPI, we grab it from XAPI directly
                iface_id = self.get_xapi_iface_id(external_ids["xs-vif-uuid"])
                p = VifPort(name, ofport, iface_id,
                            external_ids["attached-mac"], self)
                edge_ports.append(p)

        return edge_ports



