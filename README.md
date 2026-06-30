# AAP Bare-Metal RHEL 9 Provisioning via Dell iDRAC7

Provisions RHEL 9 onto a Dell PowerEdge T620 by driving iDRAC7 to boot an unattended ISO served over NFS, then configures the host with a demo web application — all orchestrated from Ansible Automation Platform (AAP).

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
│   │            │  rhel9.yml      │   demo app    │                  │
│   └───────────┘                  └───────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
```

## Environment

| Item | Value |
|---|---|
| Server | Dell PowerEdge T620 (12th gen) |
| iDRAC | iDRAC7 Enterprise, firmware 2.65.65.65 |
| iDRAC IP | `192.168.50.252` |
| T620 target IP | `192.168.50.253` |
| AAP / NFS host IP | `192.168.50.251` |
| NFS share | `/srv/iso` |
| AAP | 2.5+ (containerized), `https://aaponprem.chrislab.dev` |

### Why RHEL 9 and not RHEL 10?

The T620 uses Xeon E5-2600 v1/v2 (Sandy/Ivy Bridge), which is `x86-64-v2`. RHEL 10 requires `x86-64-v3` — its installer kernel will not boot on this CPU. There is no workaround.

### Why OMSDK/WSMan and not Redfish?

iDRAC7's Redfish implementation is too limited for OS deployment. The `dellemc.openmanage.idrac_os_deployment` module with `BootToNetworkISO` uses WSMan via OMSDK, which fully supports iDRAC7.

## Prerequisites

| Requirement | Purpose |
|---|---|
| `osbuild-composer` + `composer-cli` | Image Builder — builds the golden image ISO |
| `lorax` (`mkksiso`) | Layers the per-host kickstart onto the golden image |
| `nfs-utils` | Serves the ISO to iDRAC over NFS |
| `ansible-builder` + `podman` | Builds the custom Execution Environment |
| `ansible-navigator` | Runs playbooks locally inside the EE |

## Quick start — full demo setup

### 1. Set credentials

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Description |
|---|---|
| `AAP_HOSTNAME` | AAP gateway URL (e.g. `https://aaponprem.chrislab.dev`) |
| `AAP_TOKEN` | AAP OAuth2 personal access token |
| `IDRAC_PASSWORD` | iDRAC root password |
| `RHSM_USERNAME` | Red Hat Subscription Manager username |
| `RHSM_PASSWORD` | Red Hat Subscription Manager password |

### 2. Prepare the environment (build phase)

This runs on the AAP/NFS host and handles the entire build phase — golden image, kickstarts, ISOs, and NFS:

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

### 3. Build and push the Execution Environment

All provisioning playbooks run inside a custom EE that includes `omsdk`, `dellemc.openmanage`, and `ansible.posix`. No local Python dependencies needed.

```bash
ansible-builder build -f ansible_deployment/ee/execution-environment.yml -t quay.io/crenwick93/bmaas-ee:latest
podman push quay.io/crenwick93/bmaas-ee:latest
```

### 4. Configure AAP (Configuration as Code)

Install the required collections:

```bash
ansible-galaxy collection install -r ansible_deployment/cac/requirements.yml
```

Run the CaC script:

```bash
./ansible_deployment/scripts/cac-apply.sh
```

This creates all AAP objects in a single run:

| Object | Details |
|---|---|
| **Credential Types** | Dell iDRAC, RHSM Credentials |
| **Credentials** | T620 iDRAC, T620 SSH, Red Hat Subscription |
| **Execution Environment** | Bare Metal EE (`quay.io/crenwick93/bmaas-ee:latest`) |
| **Project** | Bare Metal Automation (this Git repo, syncs on launch) |
| **Inventory** | Bare Metal Deployment (iDRAC + T620 hosts with groups) |
| **Job Templates** | Provision RHEL 9, Wait for Install, Configure RHEL 9 |
| **Workflow** | End-to-End Bare Metal Deployment (provision → wait → configure) |

### 5. Run the demo

Launch the **End-to-End Bare Metal Deployment** workflow from the AAP UI. It runs three steps in sequence:

1. **Provision RHEL 9** — tells iDRAC to mount the ISO over NFS and boot
2. **Wait for Install** — polls until the server powers off, then boots from disk and waits for SSH
3. **Configure RHEL 9** — registers with RHSM, installs httpd, deploys the demo landing page

Once complete, browse to `http://192.168.50.253` to see the demo app.

## Running locally (without AAP)

You can also run the provisioning playbooks directly using `ansible-navigator`:

```bash
# Provision — triggers iDRAC BootToNetworkISO
ansible-navigator run playbooks/provision_rhel9.yml

# Wait for install to complete
ansible-navigator run playbooks/wait_for_install.yml

# Configure — deploy demo app
ansible-navigator run playbooks/configure_rhel9.yml
```

## Playbooks

| Playbook | Target | Purpose |
|---|---|---|
| `playbooks/prepare_environment.yml` | localhost | Builds golden image, generates kickstarts, builds ISOs, configures NFS |
| `playbooks/provision_rhel9.yml` | iDRAC (`192.168.50.252`) | Mounts ISO over NFS and boots unattended RHEL 9 install |
| `playbooks/wait_for_install.yml` | iDRAC → T620 | Polls for power off, boots from disk, verifies RHEL 9 over SSH |
| `playbooks/configure_rhel9.yml` | T620 host | Registers with RHSM, installs httpd, deploys demo landing page |

## Golden image

The golden image is defined in `golden-image/blueprint.toml` and built by Image Builder (`osbuild-composer`). It contains the organisation's baseline:

- `ansible` service account with SSH key auth and passwordless sudo
- SSH hardened (root login disabled, password auth disabled)
- `python3`, `openssh-server`, `firewalld` pre-installed
- Timezone, locale, NTP configured

The per-host kickstart (`kickstart/ks.cfg.j2`) is intentionally minimal — only hostname, network, disk layout, and root password. Everything else is baked into the golden image.

## Project structure

```
├── .env.example                          # Template for credentials
├── ansible.cfg                           # Ansible config (inventory, collections path)
├── inventory.ini                         # Local inventory (iDRAC, T620, servers)
├── group_vars/
│   └── idrac.yml                         # ISO share and image vars for iDRAC hosts
├── golden-image/
│   └── blueprint.toml                    # Image Builder blueprint
├── kickstart/
│   └── ks.cfg.j2                         # Kickstart Jinja2 template
├── playbooks/
│   ├── prepare_environment.yml           # Build phase (golden image, ISOs, NFS)
│   ├── provision_rhel9.yml               # Boot to ISO via iDRAC
│   ├── wait_for_install.yml              # Wait for install, boot from disk
│   └── configure_rhel9.yml              # Post-install config + demo app
├── ansible_deployment/
│   ├── ee/
│   │   └── execution-environment.yml     # Custom EE definition (omsdk, openmanage)
│   ├── cac/
│   │   ├── apply.yml                     # CaC entry playbook
│   │   ├── vars.yml                      # All AAP object definitions
│   │   ├── requirements.yml              # Collections needed for CaC
│   │   └── execution-environment.yml     # CaC EE definition (unused — runs locally)
│   └── scripts/
│       └── cac-apply.sh                  # Wrapper script to apply CaC
└── vault/
    ├── idrac_secrets.yml                 # Local-only iDRAC credentials (gitignored)
    └── laptop_ssh_key                    # SSH private key for T620 (gitignored)
```

## Troubleshooting

- **NFS reachability:** Validate from the iDRAC's perspective, not the laptop's. A share the laptop sees locally but the iDRAC cannot reach (firewall, SELinux, wrong export IP) is the classic failure.
- **Lifecycle Controller:** Confirm it is enabled (F10 at boot, or via iDRAC Settings). It is the engine for `BootToNetworkISO`.
- **SELinux:** If NFS mounts fail silently, check `setsebool -P nfs_export_all_ro 1` was applied.
- **Firewall:** Ensure `nfs`, `mountd`, and `rpc-bind` services are open in `firewalld`.
- **T620 IP after install:** The kickstart uses static IP `192.168.50.253`. Verify this is free on the network before provisioning.
- **EE not pulling:** If AAP can't pull the EE image, check that `podman push` succeeded and the registry is accessible from the AAP host.
