Name:		openstack-quantum-neuca
Version:	0.1
Release:	exogeni9%{?dist}
Summary:	Quantum NEuca plugin

Group:		Applications/System
License:	EPL 1.0

Source0:	neuca-%{version}.tgz

BuildArch:	noarch

BuildRequires:	python2-devel

Requires(post):   chkconfig
Requires(postun): initscripts
Requires(preun):  chkconfig
Requires(preun):  initscripts

Requires:	openstack-quantum >= 2012.1-6
Requires:	vconfig
Requires:	net-tools
Requires:	bridge-utils
Requires:	sudo

%description
Quantum provides an API to dynamically request and configure virtual
networks.

This package contains the quantum plugin that implements virtual
networks via NEuca and Open vSwitch.

%prep
%setup -q -n neuca_src

find neuca -name \*.py -exec sed -i '/\/usr\/bin\/env python/d' {} \;

%build
%{__python} -mcompileall neuca
%{__python} -O -mcompileall neuca

%install
umask 0022
mkdir -p %{buildroot}%{python_sitelib}/quantum/plugins/
cp -R neuca %{buildroot}%{python_sitelib}/quantum/plugins/

# Install execs (using hand-coded rather than generated versions)
install -p -D -m 755 neuca-agent %{buildroot}%{_bindir}/neuca-agent
install -p -D -m 755 neuca-rootwrap %{buildroot}%{_bindir}/neuca-rootwrap

# Install config
install -p -D -m 640 neuca_quantum_plugin.ini %{buildroot}%{_sysconfdir}/quantum/plugins/neuca/neuca_quantum_plugin.ini

# Install sudoers
install -p -D -m 440 neuca-sudoers %{buildroot}%{_sysconfdir}/sudoers.d/neuca

# Install policykit
install -p -D -m 644 neuca-polkit.pkla %{buildroot}%{_sysconfdir}/polkit-1/localauthority/50-local.d/50-neuca.pkla

# Install sysv init scripts
install -p -D -m 755 neuca-agent.init %{buildroot}%{_initrddir}/neuca-agent

# Configure agent to use neuca-rootwrap
sed -i 's/root_helper = sudo/root_helper = sudo neuca-rootwrap/g' %{buildroot}%{_sysconfdir}/quantum/plugins/neuca/neuca_quantum_plugin.ini

# Setup directories
install -d -m 755 %{buildroot}%{_localstatedir}/log/neuca
install -d -m 755 %{buildroot}%{_localstatedir}/run/neuca

%post
if [ $1 -eq 1 ] ; then
    # Initial installation
    /sbin/chkconfig --add neuca-agent
fi

%preun
if [ $1 -eq 0 ] ; then
    # Package removal, not upgrade
    /sbin/service neuca-agent stop >/dev/null 2>&1
    /sbin/chkconfig --del neuca-agent
fi

%postun
if [ $1 -ge 1 ] ; then
    # Package upgrade, not uninstall
    /sbin/service neuca-agent condrestart >/dev/null 2>&1 || :
fi

%files
%doc LICENSE.Eclipse
%{_bindir}/neuca-agent
%{_bindir}/neuca-rootwrap
%config(noreplace) %{_sysconfdir}/sudoers.d/neuca
%{_sysconfdir}/polkit-1/localauthority/50-local.d/50-neuca.pkla
%{_initrddir}/neuca-agent
%{python_sitelib}/quantum/plugins/neuca
%dir %{_sysconfdir}/quantum/plugins/neuca
%config(noreplace) %attr(-, root, quantum) %{_sysconfdir}/quantum/plugins/neuca/*.ini
%dir %attr(0755, quantum, quantum) %{_localstatedir}/log/neuca
%dir %attr(0755, quantum, quantum) %{_localstatedir}/run/neuca

%changelog
* Tue Apr 15 2014 Victor J. Orlikowski <vjo@cs.duke.edu> - 0.1-exogeni6
- QEMU virtio UDP optimization

* Fri Jul 5 2013 Victor J. Orlikowski <vjo@cs.duke.edu> - 0.1-exogeni5
- Bug fix for leaking tap devices

* Fri May 17 2013 Victor J. Orlikowski <vjo@cs.duke.edu> - 0.1-exogeni4
- More bug fixes...

* Mon Nov 26 2012 Victor J. Orlikowski <vjo@cs.duke.edu> - 0.1-exogeni2
- Bug fixing

* Tue Sep 18 2012 Victor J. Orlikowski <vjo@cs.duke.edu> - 0.1-exogeni1
- Initial packaging for Essex
