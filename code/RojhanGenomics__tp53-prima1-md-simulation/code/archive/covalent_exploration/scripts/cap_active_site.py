"""
اسکریپت کلاهک‌گذاری (Capping) قطعات مدل موضعی با ACE و NME
نسخه اصلاح‌شده با پاک‌سازی حافظه موقت PyMOL و حفظ پیوستگی CYQ 124
"""

from pymol import cmd, editor

cmd.reinitialize()
cmd.load("active_site_raw.pdb", "site_model")

# دریافت شماره تمامی باقی‌مانده‌ها (شامل CYQ 124)
resis_str = set()
cmd.iterate("site_model", "resis_str.add(resi)", space={"resis_str": resis_str})

# تبدیل به عدد صحیح و مرتب‌سازی
sorted_resis = sorted([int(r) for r in resis_str if r.lstrip('-').isdigit()])

if not sorted_resis:
    print("خطا: هیچ باقی‌مانده‌ای در مدل یافت نشد!")
else:
    # تفکیک قطعات پیوسته
    segments = []
    current_seg = [sorted_resis[0]]

    for r in sorted_resis[1:]:
        if r == current_seg[-1] + 1:
            current_seg.append(r)
        else:
            segments.append(current_seg)
            current_seg = [r]
    segments.append(current_seg)

    print(f"تعداد قطعات پیوسته واقعی شناسایی‌شده: {len(segments)}")
    for i, seg in enumerate(segments, 1):
        has_cyq = " (شامل باقی‌مانده کووالانت CYQ 124)" if 124 in seg else ""
        print(f"  قطعه {i}: باقی‌مانده‌های {seg[0]} تا {seg[-1]}{has_cyq}")

    print("\nدر حال اضافه کردن کلاهک‌های ACE و NME...")
    for i, seg in enumerate(segments, 1):
        n_term_resi = seg[0]
        c_term_resi = seg[-1]

        # 1. کلاهک N-terminal (ACE)
        n_sel = f"site_model and resi {n_term_resi} and name N"
        if cmd.count_atoms(n_sel) > 0:
            try:
                cmd.delete("not site_model")  # پاک‌سازی اشیاء موقت قبلی
                editor.attach_fragment(n_sel, "ace", 1, 0)
                cmd.delete("not site_model")
                print(f"  - کلاهک ACE اضافه شد به انتهای N (باقی‌مانده {n_term_resi})")
            except Exception as e:
                print(f"  ! هشدار کلاهک ACE برای باقی‌مانده {n_term_resi}: {e}")

        # 2. کلاهک C-terminal (NME)
        c_sel = f"site_model and resi {c_term_resi} and name C"
        if cmd.count_atoms(c_sel) > 0:
            try:
                cmd.delete("not site_model")  # پاک‌سازی اشیاء موقت قبلی
                editor.attach_fragment(c_sel, "nme", 1, 0)
                cmd.delete("not site_model")
                print(f"  - کلاهک NME اضافه شد به انتهای C (باقی‌مانده {c_term_resi})")
            except Exception as e:
                print(f"  ! هشدار کلاهک NME برای باقی‌مانده {c_term_resi}: {e}")

    # اضافه کردن هیدروژن‌های کلاهک‌ها
    cmd.h_add("site_model")
    
    # ذخیره ساختار نهایی
    cmd.save("active_site_capped.pdb", "site_model")
    print("\nفایل کلاهک‌گذاری‌شده با موفقیت ذخیره شد: active_site_capped.pdb")
