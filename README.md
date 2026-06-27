# AAP Bare-Metal RHEL 9 Provisioning via Dell iDRAC7

Provisions RHEL 9 onto a Dell PowerEdge T620 by driving iDRAC7 to boot an unattended ISO served over NFS — orchestrated from Ansible Automation Platform (AAP) 2.6.

## Prerequisites

| Requirement | Purpose |
|---|---|
| `lorax` package (`dnf install lorax`) | Provides `mkksiso` to embed the kickstart into the ISO |
| `omsdk` Python package | Required by the `dellemc.openmanage` Ansible modules for WSMan/iDRAC communication |
| `dellemc.openmanage` collection (9.x) | Ansible collection with `idrac_os_deployment` module |
| Stock RHEL 9 DVD ISO (`rhel-9-x86_64-dvd.iso`) | Base ISO before kickstart injection |
| NFS server packages (`nfs-utils`) | Serves the ISO to iDRAC over NFS |

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

## Step-by-step

### 1. Build the unattended ISO

First, generate a root password hash and paste it into `kickstart/ks.cfg` at the `rootpw --iscrypted` line:

```bash
python3 -c 'import crypt; print(crypt.crypt("YourDemoPass", crypt.mksalt(crypt.METHOD_SHA512)))'
```

Then build the ISO (requires `lorax` installed):

```bash
./scripts/build-iso.sh /path/to/rhel-9-x86_64-dvd.iso
```

This embeds the kickstart and writes the output to `/srv/iso/rhel9-unattended.iso`.

### 2. Start the NFS share

```bash
./scripts/setup-nfs.sh
```

This creates `/srv/iso`, exports it read-only to the iDRAC IP (`192.168.50.252`), enables `nfs-server`, opens the firewall, and sets the required SELinux boolean.

### 3. Encrypt the vault

Edit `vault/idrac_secrets.yml` with the real iDRAC root password, then encrypt:

```bash
ansible-vault encrypt vault/idrac_secrets.yml
```

Optionally, store the vault password in `.vault_pass` (already in `.gitignore`) and uncomment the `vault_password_file` line in `ansible.cfg`.

### 4. Install dependencies (local testing)

```bash
pip install -r requirements.txt
ansible-galaxy collection install -r collections/requirements.yml
```

### 5. Run the playbook (local)

```bash
ansible-playbook provision_rhel9.yml --ask-vault-pass
```

### 6. AAP wiring

To run this from AAP instead of the CLI:

- **Execution Environment:** Build a custom EE that includes `omsdk` (pip) and the `dellemc.openmanage` collection. The stock EE does not ship OMSDK.
- **Credential:** Store the iDRAC root password as a vault credential or AAP custom credential type — do not put it in extra vars in clear.
- **Project:** Point AAP at this Git repo.
- **Job Template:** Create a template that runs `provision_rhel9.yml` against the `idrac` inventory group. This becomes the single "Launch" button for the demo.

## Runtime flow

When the playbook runs (starting from the T620 powered OFF):

1. Ansible connects to iDRAC `192.168.50.252` over HTTPS/WSMan.
2. A Lifecycle Controller `BootToNetworkISO` job is created.
3. iDRAC mounts `rhel9-unattended.iso` from `192.168.50.251:/srv/iso` and exposes it as a virtual CD-ROM.
4. iDRAC sets one-time boot to CD and powers the T620 on.
5. The RHEL 9 installer boots; the embedded kickstart drives an unattended install.
6. The server reboots into a fully installed RHEL 9. The ISO auto-detaches after the `expose_duration` (60 minutes).

## Troubleshooting

- **NFS reachability:** Validate from the iDRAC's perspective, not the laptop's. A share the laptop sees locally but the iDRAC cannot reach (firewall, SELinux, wrong export IP) is the classic failure and won't surface until `BootToNetworkISO` runs.
- **Lifecycle Controller:** Confirm it is enabled (F10 at boot, or via iDRAC Settings → Lifecycle Controller). It is the engine for the entire `BootToNetworkISO` operation.
- **SELinux:** If NFS mounts fail silently, check `setsebool -P nfs_export_all_ro 1` was applied.
- **Firewall:** Ensure `nfs`, `mountd`, and `rpc-bind` services are open in `firewalld`.
