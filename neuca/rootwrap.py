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
# @author: Victor J. Orlikowski, Duke University
#
# Credit to the following authors, from whose work this was derived:
# The OpenStack developers

from quantum.rootwrap import filters

filterlist = [
    # quantum/plugins/neuca/agent/ovs_network.py:
    #   "ovs-vsctl", "--timeout=2", ...
    filters.CommandFilter("/usr/bin/ovs-vsctl", "root"),
    filters.CommandFilter("/bin/ovs-vsctl", "root"),

    # quantum/plugins/neuca/agent/ovs_network.py:
    #   "ovs-ofctl", cmd, self.br_name, args
    filters.CommandFilter("/usr/bin/ovs-ofctl", "root"),
    filters.CommandFilter("/bin/ovs-ofctl", "root"),

    # quantum/plugins/neuca/agent/neuca_quantum_agent.py:
    filters.CommandFilter("/sbin/ifconfig", "root"),

    # quantum/plugins/neuca/agent/neuca_quantum_agent.py:
    filters.CommandFilter("/sbin/vconfig", "root"),

    # quantum/plugins/neuca/agent/neuca_quantum_agent.py:
    filters.CommandFilter("/usr/sbin/tunctl", "root"),
    ]
