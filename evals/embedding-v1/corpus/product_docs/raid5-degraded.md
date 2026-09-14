# RAID5 degraded-mode write limits

Model: DS920+

On a DS920+ volume using RAID5, a degraded array can stay mounted for read access. Continued writes increase the chance of a second-disk failure and unrecoverable data loss. Do not format the volume, rebuild onto the degraded set, or run a repair utility until a healthy replacement disk is installed and the array returns to normal.
