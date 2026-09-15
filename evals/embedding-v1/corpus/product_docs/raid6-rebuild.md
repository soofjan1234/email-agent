# RAID6 rebuild after a single disk failure

Model: DS1821+

A DS1821+ RAID6 storage pool can survive one disk failure and start a rebuild after a replacement disk is inserted. Rebuild time depends on pool size and load. RAID6 is not RAID5: a RAID6 pool should not be treated as if a second failure is immediately fatal, but heavy write load during rebuild should still be reduced.
