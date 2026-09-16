# rclone Dropbox mount

A durable, read-write FUSE mount of Dropbox at `/home/moltron/dropbox` on
`valet`, so `moltron` can read and write binary project artifacts as plain
files. Installed by `ansible/roles/rclone-dropbox`. Separate from the
existing Dropbox integration used for backups — this uses its own dedicated
Dropbox app and its own Bitwarden secrets, so a leak of one never exposes
the other.

## Credential setup (one-time, manual)

Dropbox OAuth needs a browser-based consent step that can't be done
headlessly on `valet`, so this part is done by hand, not by Ansible:

1. In the [Dropbox App Console](https://www.dropbox.com/developers/apps),
   create a new app:
   - Permission type: **Full Dropbox** (not "App folder" — this mount
     exposes the whole account, a deliberate choice for this integration).
   - Scopes: file content read + write, plus metadata read (whatever the
     console groups as the standard file-access scopes).
   - Note the app's **client id** and **client secret**.
2. On a machine with a browser (not `valet`), with `rclone` installed:
   ```
   rclone authorize "dropbox" <client_id> <client_secret>
   ```
   Complete the OAuth consent in the browser it opens. rclone prints a
   token JSON blob to the terminal when done.
3. Add three secrets to this project's Bitwarden Secrets Manager project:
   - `dropbox_rclone_client_id` — the client id from step 1
   - `dropbox_rclone_client_secret` — the client secret from step 1
   - `dropbox_rclone_token` — the token JSON blob from step 2
4. Update the placeholder UUIDs in `ansible/playbooks/group_vars/all.yaml`
   (`dropbox_rclone_client_id`, `dropbox_rclone_client_secret`,
   `dropbox_rclone_token`) to point at the real secret UUIDs.

Ansible only ever consumes these three secrets — it never generates or
handles raw OAuth material, and nothing Dropbox-related is committed to
git.

## Mount flags and their trade-offs

The systemd service runs:
```
rclone mount dropbox: /home/moltron/dropbox \
  --vfs-cache-mode writes \
  --vfs-cache-max-size 1G \
  --dir-cache-time 1m \
  --poll-interval 30s \
  --umask 077
```

| Flag | Choice | Trade-off |
| --- | --- | --- |
| `--vfs-cache-mode` | `writes` | Needed for correct read-write FUSE semantics — without it, apps that seek or rewrite partway through a file can corrupt uploads. `full` would be safer still (caches reads too) but needlessly duplicates the whole Dropbox account onto valet's 32GB disk. `off` only works for read-only use. |
| `--vfs-cache-max-size` | `1G` | Bounds local disk usage from the write cache on a small VM disk. |
| `--dir-cache-time` | `1m` | How long directory listings are cached before rclone re-checks Dropbox — lower means fresher listings at the cost of more API calls. |
| `--poll-interval` | `30s` | How often rclone polls Dropbox for remote-side changes (Dropbox has no push/webhook support in rclone's backend) — trades API call frequency against how fast changes made outside `moltron` (e.g. from your phone) show up in the mount. |
| `--umask` | `077` | Only `moltron` should ever read/write this mount; no `--allow-other` is used since no other local user needs access. |

## Operational checks

```
systemctl --user -M moltron@ status rclone-dropbox-mount   # or, logged in as moltron:
systemctl --user status rclone-dropbox-mount
journalctl --user -u rclone-dropbox-mount
mountpoint /home/moltron/dropbox
ls /home/moltron/dropbox
```

`moltron` has lingering enabled (`loginctl enable-linger moltron`, set by
the `moltron-user` role), so this systemd `--user` service starts at boot
without anyone logging in.

## Rollback

```
systemctl --user disable --now rclone-dropbox-mount
fusermount -u /home/moltron/dropbox   # if still mounted after stopping the unit
rm /home/moltron/.config/rclone/rclone.conf
```

Then, outside `valet`:
- Revoke the app from Dropbox's [connected apps](https://www.dropbox.com/account/connected_apps) page.
- Delete the three `dropbox_rclone_*` secrets from Bitwarden Secrets Manager.
- Remove the corresponding lookups from `ansible/playbooks/group_vars/all.yaml`
  and drop `rclone-dropbox` from `ansible/playbooks/main.yaml`'s role list.
