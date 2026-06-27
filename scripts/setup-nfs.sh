#!/usr/bin/env bash
set -euo pipefail
sudo mkdir -p /srv/iso
echo "/srv/iso 192.168.50.252(ro,sync,no_root_squash,no_subtree_check)" \
  | sudo tee /etc/exports.d/iso.exports
sudo exportfs -ra
sudo systemctl enable --now nfs-server
sudo firewall-cmd --add-service={nfs,mountd,rpc-bind} --permanent
sudo firewall-cmd --reload
sudo setsebool -P nfs_export_all_ro 1
echo "NFS export ready for iDRAC at 192.168.50.252"
