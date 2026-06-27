# AAP Bare-Metal RHEL 9 Provisioning via Dell iDRAC7

Provisions RHEL 9 onto a Dell PowerEdge T620 by driving iDRAC7 to boot an unattended ISO served over NFS, then configures the host with a demo web application — all orchestrated from Ansible Automation Platform (AAP) 2.6.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BUILD PHASE (one-time)                       │
│                                                                     │
│   blueprint.toml ──► Image Builder ──► rhel9-golden.iso             │
│   (ansible user,       (osbuild-         (golden image              │
│    SSH hardening,       composer)          with baseline)            │
│    packages)                                  │                     │
│                                               ▼                     │
│   inventory.ini ──► ks.cfg.j2 ──► t620-demo.cfg ──► mkksiso        │
│   (hostname, IP,     (Jinja2       (per-host          │             │
│    disk layout)       template)     kickstart)         ▼             │
│                                              t620-demo-unattended.iso│
│                                                       │             │
│                                                       ▼             │
│                                                  /srv/iso (NFS)     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     DEPLOY PHASE (per server)                       │
│                                                                     │
│   ┌───────────┐    HTTPS/WSMan     ┌───────────┐                    │
│   │    AAP     │ ─────────────────► │  iDRAC7   │                    │
│   │  (laptop)  │  BootToNetworkISO  │ .50.252   │                    │
│   │  .50.251   │                    └─────┬─────┘                    │
│   └───────────┘                          │                          │
│        │                          mounts ISO                        │
│        │                          over NFS                          │
│        │                                 │                          │
│   /srv/iso ◄─────────────────────────────┘                          │
│   (NFS share)                            │                          │
│                                    powers on T620                   │
│                                    boots virtual CD                 │
│                                          │                          │
│                                          ▼                          │
│                                 ┌─────────────────┐                 │
│                                 │   RHEL 9 Install │                 │
│                                 │   (unattended)   │                 │
│                                 └────────┬────────┘                 │
│                                          │                          │
│                                       reboot                        │
│                                          │                          │
│                                          ▼                          │
│   ┌───────────┐       SSH        ┌───────────────┐                  │
│   │    AAP     │ ──────────────► │     T620       │                  │
│   │  (laptop)  │  configure_     │   RHEL 9 +    │                  │
│   │           │  rhel9.yml      │   demo app    │                  │
│   └───────────┘                  └───────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

| Requirement | Purpose |
|---|---|
| `osbuild-composer` + `composer-cli` | Image Builder — builds the golden image ISO |
| `lorax` (`mkksiso`) | Layers the per-host kickstart onto the golden image |
| `omsdk` Python package | Required by `dellemc.openmanage` for WSMan/iDRAC communication |
| `dellemc.openmanage` collection (9.x) | Ansible collection with `idrac_os_deployment` module |
| `nfs-utils` | Serves the ISO to iDRAC over NFS |
| `infra.aap_configuration` collection | Configuration as Code — creates all AAP objects |

### Why RHEL 9 and not RHEL 10?

The T620 uses Xeon E5-2600 v1/v2 (Sandy/Ivy Bridge), which is `x86-64-v2`. RHEL 10 requires `x86-64-v3` — its installer kernel will not boot on this CPU. There is no workaround.

### Why OMSDK/WSMan and not Redfish?

iDRAC7's Redfish implementation is too limited for OS deployment. The `dellemc.openmanage.idrac_os_deployment` module with `BootToNetworkISO` uses WSMan via OMSDK, which fully supports iDRAC7.

## Environment

| Item | Value |
|---|---|
| Server | Dell PowerEdge T620 (12th gen) |
| iDRAC | iDRAC7 Enterprise, firmware 2.65.65.65 |
| iDRAC IP | `192.168.50.252` |
| AAP / NFS host IP | `192.168.50.251` |
| NFS share | `/srv/iso` |
| AAP | 2.6 (containerized), `https://aaponprem.chrislab.dev` |

## Playbooks

| Playbook | Target | Purpose |
|---|---|---|
| `playbooks/prepare_environment.yml` | localhost | Builds golden image, generates kickstarts, builds ISOs, configures NFS |
| `playbooks/provision_rhel9.yml` | iDRAC (`192.168.50.252`) | Mounts ISO over NFS and boots unattended RHEL 9 install |
| `playbooks/wait_for_install.yml` | T620 host | Polls SSH until the host comes online, confirms RHEL 9 |
| `playbooks/configure_rhel9.yml` | T620 host | Installs httpd, deploys a demo landing page, opens firewall |
| `playbooks/test_idrac.yml` | iDRAC (`192.168.50.252`) | Non-invasive EE and connectivity test |

## Step-by-step

### 1. Set credentials

Copy the example environment file and fill in the blanks:

```bash
cp .env.example .env
# Edit .env — set AAP_TOKEN and IDRAC_PASSWORD
```

Set the root password hash in the inventory (used by kickstart generation):

```bash
# Generate a hash
python3 -c 'import crypt; print(crypt.crypt("YourDemoPass", crypt.mksalt(crypt.METHOD_SHA512)))'

# Paste the output into inventory.ini under [servers]
# t620-demo ks_hostname=t620-demo ks_root_password_hash=<paste here>
```

Encrypt the iDRAC vault:

```bash
ansible-vault encrypt vault/idrac_secrets.yml
```

### 2. Install Ansible dependencies

```bash
pip install -r requirements.txt
ansible-galaxy collection install -r collections/requirements.yml
```

### 3. Prepare the environment

This single playbook handles the entire build phase — golden image, kickstarts, ISOs, and NFS:

```bash
ansible-playbook playbooks/prepare_environment.yml
```

What it does:
1. Installs prerequisites (`lorax`, `nfs-utils`, `osbuild-composer`, etc.)
2. Builds the golden image via Image Builder (ansible user, SSH hardening, baseline packages)
3. Generates per-host kickstarts from `inventory.ini` using the Jinja2 template
4. Layers each kickstart onto the golden image ISO with `mkksiso`
5. Exports `/srv/iso` over NFS to the iDRAC, opens the firewall, sets SELinux

To skip the golden image build and use a stock RHEL 9 DVD instead:

```bash
ansible-playbook playbooks/prepare_environment.yml -e golden_image_build=false -e stock_iso=/path/to/rhel-9-dvd.iso
```

### 4. Provision and configure

```bash
# Provision — triggers iDRAC BootToNetworkISO
ansible-playbook playbooks/provision_rhel9.yml --ask-vault-pass

# Wait for install to complete (polls SSH)
ansible-playbook playbooks/wait_for_install.yml

# Configure — deploy demo app
ansible-playbook playbooks/configure_rhel9.yml
```

## Golden image

The golden image is defined in `golden-image/blueprint.toml` and built by Image Builder (`osbuild-composer`). It contains the organisation's baseline:

- `ansible` service account with SSH key auth and passwordless sudo
- SSH hardened (root login disabled, password auth disabled)
- `python3`, `openssh-server`, `firewalld` pre-installed
- Timezone, locale, NTP configured

The per-host kickstart (`kickstart/ks.cfg.j2`) is intentionally minimal — only hostname, network, disk layout, and root password. Everything else is baked into the golden image.

To add more servers, add entries to the `[servers]` group in `inventory.ini`:

```ini
[servers]
t620-demo   ks_hostname=t620-demo   ks_root_password_hash=$6$...
r730-web01  ks_hostname=r730-web01  ks_ip=10.0.1.20  ks_gateway=10.0.1.1  ks_root_password_hash=$6$...
```

Then re-run `ansible-playbook playbooks/prepare_environment.yml` — one ISO per host is generated automatically.

## AAP wiring (Configuration as Code)

The `ansible_deployment/` directory automates AAP setup using `infra.aap_configuration`. One script creates all objects:

### Quick start

1. Fill in `.env` (see `.env.example`)

2. Install the CaC collection:

```bash
ansible-galaxy collection install infra.aap_configuration
```

3. Run:

```bash
./ansible_deployment/scripts/cac-apply.sh
```

This creates in AAP:
- **Organization:** Bare Metal Provisioning
- **Project:** Bare Metal Automation (this Git repo)
- **Inventories:** iDRAC Management + Bare Metal Hosts
- **Credentials:** Dell iDRAC (custom type) + T620 SSH (Machine)
- **Execution Environment:** Bare Metal EE (custom image with `omsdk` + `dellemc.openmanage`)
- **Job Templates:** Provision RHEL 9, Wait for Install, Configure RHEL 9
- **Workflow:** End-to-End Bare Metal Deployment (provision > wait > configure)

### Custom Execution Environment

All playbooks run inside a custom EE that includes `omsdk`, `dellemc.openmanage`, and `ansible.posix`. No local Python dependencies are needed — everything runs in the container.

**Build the EE** (requires `ansible-builder` and `podman`):

```bash
ansible-builder build -f ansible_deployment/ee/execution-environment.yml -t quay.io/crenwick93/bmaas-ee:latest
```

**Push to registry** so AAP can pull it:

```bash
podman push quay.io/crenwick93/bmaas-ee:latest
```

**Test locally** with `ansible-navigator` (runs inside the EE, nothing installed on your machine):

```bash
ansible-navigator run playbooks/test_idrac.yml
```

The EE definition is at `ansible_deployment/ee/execution-environment.yml`. The `context/` directory generated by `ansible-builder` is a build artifact and is excluded from Git.

## Troubleshooting

- **NFS reachability:** Validate from the iDRAC's perspective, not the laptop's. A share the laptop sees locally but the iDRAC cannot reach (firewall, SELinux, wrong export IP) is the classic failure.
- **Lifecycle Controller:** Confirm it is enabled (F10 at boot, or via iDRAC Settings). It is the engine for `BootToNetworkISO`.
- **SELinux:** If NFS mounts fail silently, check `setsebool -P nfs_export_all_ro 1` was applied.
- **Firewall:** Ensure `nfs`, `mountd`, and `rpc-bind` services are open in `firewalld`.
- **T620 IP after install:** The kickstart uses DHCP (`--device=link`). Check your router/DHCP server for the lease, or look at the iDRAC console to find the assigned IP.
