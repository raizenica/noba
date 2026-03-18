Name:           noba
Version:        3.3.0
Release:        1%{?dist}
Summary:        NOBA Command Center - Homelab automation dashboard
License:        GPLv3
URL:            https://github.com/raizenica/noba
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel
# Dependencies derived from NOBA's install.sh
Requires:       python3, bash, rsync, rclone, jq, yq, dialog, msmtp

%description
NOBA // Command Center is a comprehensive Bash-based system automation,
backup, and monitoring toolkit designed for Linux systems.

%prep
%autosetup

%build
# Nothing to build - pure Bash/Python/JavaScript application

%install
# Create standard system directory structure
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_libexecdir}/noba
install -d %{buildroot}%{_datadir}/noba
install -d %{buildroot}/usr/lib/systemd/user

# Copy executable wrappers
install -m 755 bin/noba %{buildroot}%{_bindir}/noba
install -m 755 bin/noba-web %{buildroot}%{_bindir}/noba-web

# Copy core scripts and libraries
cp -r libexec/* %{buildroot}%{_libexecdir}/noba/
cp -r lib %{buildroot}%{_libexecdir}/noba/ 2>/dev/null || true

# Copy web assets
cp -r share/* %{buildroot}%{_datadir}/noba/

# Install systemd user units and rewrite paths for system-wide installation
cp systemd/* %{buildroot}/usr/lib/systemd/user/
sed -i 's|${HOME}/.local/libexec/noba|%{_libexecdir}/noba|g' %{buildroot}/usr/lib/systemd/user/*.service
sed -i 's|${HOME}/.local/bin|%{_bindir}|g' %{buildroot}/usr/lib/systemd/user/*.service

%files
%{_bindir}/noba
%{_bindir}/noba-web
%{_libexecdir}/noba/
%{_datadir}/noba/
/usr/lib/systemd/user/*
%doc docs/README.md

%changelog
* Wed Mar 18 2026 NOBA Maintainer <admin@example.com> - 3.3.0-1
- Initial RPM packaging pipeline
