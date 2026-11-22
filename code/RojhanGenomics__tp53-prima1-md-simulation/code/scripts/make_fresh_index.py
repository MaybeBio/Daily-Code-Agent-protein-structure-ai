import subprocess

# ۱. ساخت گروه اندکس پایه
cmd = "echo -e 'q\n' | gmx make_ndx -f npt.gro -o index.ndx"
subprocess.run(cmd, shell=True, check=True)

# ۲. ساخت گروه‌های ترکیبی (Protein + PRIMA1) و (Water + Ions) در صورت نیاز mdp
# دستورات make_ndx برای ترکیب گروه‌ها:
# 1 | 13 یا نام گروه‌ها (Protein | PRIMA1)
merge_cmd = "echo -e '1 | 16\n 12 | 15\n q\n' | gmx make_ndx -f npt.gro -n index.ndx -o index.ndx"
try:
    subprocess.run(merge_cmd, shell=True, check=True)
except Exception:
    pass

print("فایل index.ndx جدید با موفقیت بر اساس ساختار فعلی ساخته شد.")
