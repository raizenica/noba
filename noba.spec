Name:           noba
Version:        2.0.0
Release:        1%{?dist}
Summary:        NOBA Command Center - Infrastructure management platform
License:        MIT
URL:            https://github.com/raizenica/noba-ce
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3 >= 3.10, bash >= 4.0

%description
NOBA Command Center is a self-hosted infrastructure management platform
with real-time monitoring, self-healing automation, remote agents, and
40+ integrations. Built with FastAPI and Vue 3.

%prep
%autosetup

%build
# Nothing to compile — Python + pre-built Vue frontend

%install
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_libexecdir}/noba/web
install -d %{buildroot}%{_datadir}/noba

# CLI wrappers
install -m 755 bin/noba %{buildroot}%{_bindir}/noba
install -m 755 bin/noba-web %{buildroot}%{_bindir}/noba-web

# Automation scripts
cp -r libexec/* %{buildroot}%{_libexecdir}/noba/

# Web application (server + frontend)
cp -r share/noba-web/* %{buildroot}%{_libexecdir}/noba/web/

%files
%license LICENSE
%doc README.md
%{_bindir}/noba
%{_bindir}/noba-web
%{_libexecdir}/noba/
%{_datadir}/noba/

%changelog
* Sun Mar 23 2026 Raizen <admin@example.com> - 2.0.0-1
- Full platform rewrite: FastAPI backend, Vue 3 frontend
- Self-healing pipeline, remote agents, 40+ integrations
- Self-update system, multi-user RBAC, 7 themes
