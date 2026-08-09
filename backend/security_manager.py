"""
security_manager.py  –  Temp-file tracking, cleanup, status reporting.
"""

import os, glob, shutil, time


class SecurityManager:

    def status(self, *folders) -> dict:
        total_files = 0
        total_bytes = 0
        breakdown   = {}

        for folder in folders:
            if not os.path.exists(folder):
                continue
            files = [f for f in glob.glob(os.path.join(folder, "**"), recursive=True)
                     if os.path.isfile(f)]
            size  = sum(os.path.getsize(f) for f in files if os.path.exists(f))
            name  = os.path.basename(folder)
            breakdown[name] = {"files": len(files), "size_kb": round(size / 1024, 2)}
            total_files += len(files)
            total_bytes += size

        return {
            "total_temp_files"   : total_files,
            "total_size_kb"      : round(total_bytes / 1024, 2),
            "folders"            : breakdown,
            "local_processing"   : True,
            "permanent_storage"  : False,
            "auto_delete_minutes": 15,
        }

    def cleanup(self, *folders) -> dict:
        deleted = 0
        errors  = []
        for folder in folders:
            if not os.path.exists(folder):
                continue
            for item in glob.glob(os.path.join(folder, "*")):
                try:
                    if os.path.isfile(item):
                        os.remove(item)
                    elif os.path.isdir(item):
                        shutil.rmtree(item)
                    deleted += 1
                except Exception as e:
                    errors.append(str(e))
        return {
            "deleted": deleted,
            "errors" : errors,
            "message": f"Deleted {deleted} temporary item(s).",
        }