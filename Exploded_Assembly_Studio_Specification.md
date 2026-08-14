# Exploded Assembly Studio for Blender

## 1. هدف پروژه

ساخت یک Blender Add-on برای تبدیل یک مدل assembled به یک **Exploded View** و ایجاد انیمیشن رفت و برگشت بین این دو حالت.

هدف اصلی این ابزار، استفاده در رندر و انیمیشن محصولات مکانیکی و الکترونیکی است؛ برای مثال:

- تجهیزات صنعتی
- قطعات مکانیکی
- PCB و محصولات الکترونیکی
- Enclosure
- موتور و گیربکس
- تجهیزات شبکه
- محصولات قابل مونتاژ

Workflow مورد نظر:

```text
Assembled Model
      ↓
Explode Animation
      ↓
Exploded View
      ↓
Assemble Animation
      ↓
Assembled Model
```

---

# 2. سناریوی اصلی استفاده

کاربر یک مدل کامل را در Blender وارد می‌کند.

مثلاً:

```text
          Screw
            │
          Washer
            │
       ┌─────────┐
       │  Cover  │
       └─────────┘
            │
       ┌─────────┐
       │   PCB   │
       └─────────┘
            │
       ┌─────────┐
       │  Case   │
       └─────────┘
```

کاربر وضعیت فعلی را به عنوان **Assembly Position** ذخیره می‌کند.

سپس با انتخاب گزینه Explode، قطعات از محل اصلی خود فاصله می‌گیرند:

```text
        Screw
          ↑

        Washer
          ↑

        Cover
          ↑

         PCB
          ↑

        Case
```

این حرکت باید به صورت Animation ساخته شود.

سپس با Assemble:

```text
Exploded
   ↓
Animation
   ↓
Assembled
```

قطعات دقیقاً به Transform اولیه خود برمی‌گردند.

---

# 3. اصل مهم طراحی

Add-on نباید در نسخه اول تلاش کند مفهوم مکانیکی Assembly را از روی مدل حدس بزند.

یعنی لازم نیست بفهمد:

- این پیچ متعلق به کدام سوراخ است
- این واشر روی کدام شفت قرار دارد
- این قطعه باید داخل کدام قطعه قرار بگیرد

در نسخه اول، وضعیت فعلی مدل به عنوان **Ground Truth** ذخیره می‌شود.

برای هر Object این اطلاعات ذخیره می‌شود:

- Location
- Rotation
- Scale

بنابراین:

```text
Current Transform
       ↓
Save Assembly State
       ↓
Generate Exploded Transform
```

و هنگام Assemble:

```text
Exploded Transform
       ↓
Saved Assembly Transform
```

---

# 4. رابط کاربری

یک پنل در:

```text
3D Viewport
    → Sidebar (N)
        → Exploded
```

قرار بگیرد.

ساختار پیشنهادی:

```text
┌──────────────────────────────┐
│   EXPLODED ASSEMBLY STUDIO   │
├──────────────────────────────┤
│ Source                       │
│                              │
│ ○ Selected Objects           │
│ ○ Collection                 │
│                              │
├──────────────────────────────┤
│ Explosion                    │
│                              │
│ Distance:       [ 2.0 ]      │
│ Direction:      [From Center]│
│                              │
│ Rotation:       [ 0° ]       │
│ Rotation Axis:  [ Z ]        │
│                              │
├──────────────────────────────┤
│ Animation                    │
│                              │
│ Start Frame:    [ 1 ]        │
│ End Frame:      [ 60 ]       │
│ Interpolation:  [Bezier]     │
│                              │
├──────────────────────────────┤
│ Assembly State               │
│                              │
│ [ Set Assembly Position ]    │
│                              │
│ [ EXPLODE ]  [ ASSEMBLE ]    │
│                              │
│ [ Clear Animation ]          │
└──────────────────────────────┘
```

---

# 5. Source Selection

دو روش برای انتخاب قطعات:

## A. Selected Objects

فقط Mesh Objectهایی که کاربر انتخاب کرده است.

مثلاً:

```text
Select:
- PCB
- Case
- Cover
- Screws
- Heatsink
```

و سپس Explode.

## B. Collection

کاربر یک Collection انتخاب می‌کند.

مثلاً:

```text
PRODUCT_ASSEMBLY
├── Case
├── PCB
├── Heatsink
├── Fan
├── Screws
├── Connector
└── Cover
```

Add-on تمام Mesh Objectهای داخل Collection را پردازش می‌کند.

---

# 6. Explosion Direction

حداقل سه حالت:

## 6.1 From Center

مرکز Assembly محاسبه شود.

برای هر Object:

```text
Direction = Object Center - Assembly Center
```

سپس Object در همان جهت حرکت کند.

مثال:

```text
             ↑
             │
       ←──── ● ────→
             │
             ↓
```

این حالت باید حالت پیش‌فرض باشد.

---

## 6.2 World Axis

کاربر انتخاب کند:

```text
X
Y
Z
```

قطعات در راستای Axis انتخاب‌شده Explode شوند.

---

## 6.3 Local Axis

هر Object بر اساس Local Axis خودش حرکت کند.

برای مثال:

```text
Local Z
   ↑
   │
 [Object]
```

این حالت برای قطعات مکانیکی جهت‌دار بسیار مفید است.

---

# 7. Explosion Distance

پارامتر:

```text
Explode Distance
```

مشخص می‌کند قطعات چه مقدار از محل اصلی خود فاصله بگیرند.

مثلاً:

```text
Distance = 0.5
Distance = 1.0
Distance = 2.0
Distance = 5.0
```

Distance باید بر اساس Unit سیستم Blender کار کند.

---

# 8. Animation

نسخه اول باید دو Animation بسازد.

## Explode

```text
Frame 1
   ↓
Assembled

Frame 60
   ↓
Exploded
```

## Assemble

```text
Frame 1
   ↓
Exploded

Frame 60
   ↓
Assembled
```

کاربر بتواند:

- Start Frame
- End Frame
- Interpolation

را تغییر دهد.

---

# 9. Interpolation

حداقل:

```text
Bezier
Linear
Sine
```

پیشنهاد پیش‌فرض:

```text
Bezier
```

برای حرکت نرم و حرفه‌ای.

---

# 10. Rotation During Explosion

امکان اضافه کردن Rotation اختیاری.

مثلاً:

```text
Rotation = 45°
Axis = Z
```

در هنگام Explode، Object علاوه بر Translation کمی Rotate شود.

این قابلیت برای رندرهای تبلیغاتی بسیار مفید است.

مثلاً:

```text
         ↗
      [PCB]
        ↻

         ↓

      [PCB]
```

---

# 11. حفظ Transform اصلی

این بخش بسیار مهم است.

قبل از ایجاد Animation باید برای هر Object اطلاعات زیر ذخیره شود:

```text
Assembly Location
Assembly Rotation
Assembly Scale
```

بنابراین حتی اگر کاربر چند بار Explode و Assemble کند، مدل نباید از محل اصلی خود خارج شود.

---

# 12. Object Parenting

نسخه اول بهتر است Objectهای Parent شده را با احتیاط پردازش کند.

اگر Object دارای Parent باشد:

```text
Parent
  │
  ├── Child A
  ├── Child B
  └── Child C
```

Transform باید به شکلی مدیریت شود که حرکت World Space خراب نشود.

در نسخه‌های بعدی می‌توان سیستم مخصوص Hierarchy طراحی کرد.

---

# 13. Auto Sequence

این قابلیت برای نسخه دوم پیشنهاد می‌شود.

هدف:

```text
1 → Bottom Case
2 → PCB
3 → Connector
4 → Heatsink
5 → Cover
6 → Screws
```

Add-on بتواند برای قطعات ترتیب ایجاد کند.

روش‌های احتمالی:

### Distance Based

قطعات بر اساس فاصله از مرکز مرتب شوند.

### Manual Order

کاربر Objectها را به ترتیب انتخاب کند.

### Collection Order

ترتیب بر اساس ترتیب Objectها در Collection باشد.

---

# 14. Advanced Exploded View

نسخه‌های بعدی می‌توانند به جای یک حرکت ساده، چند مرحله بسازند.

مثلاً:

```text
Stage 1
Remove Cover

Stage 2
Move PCB

Stage 3
Remove Heatsink

Stage 4
Remove Connector

Stage 5
Separate Screws
```

Timeline:

```text
1────30────60────90────120────150

   Cover
       PCB
             Heatsink
                     Connector
                              Screws
```

این برای ویدیوهای صنعتی بسیار جذاب خواهد بود.

---

# 15. Assembly Order

در نسخه پیشرفته، هر Object می‌تواند یک Order داشته باشد:

```text
Object        Order
--------------------
Case          1
PCB           2
Heatsink      3
Connector     4
Cover         5
Screw         6
```

و Animation به صورت Sequential ساخته شود.

---

# 16. Exploded View Rendering

در آینده Add-on می‌تواند برای Product Visualization نیز امکانات داشته باشد.

مثلاً:

- Camera Preset
- Studio Lighting
- Depth of Field
- Product Turntable
- Exploded View Camera
- Orthographic Technical Camera

---

# 17. قابلیت پیشنهادی برای Mechanical CAD

یکی از اهداف مهم آینده، پشتیبانی بهتر از مدل‌های CAD است.

مدل ممکن است از:

- STEP
- IGES
- SolidWorks
- Fusion 360
- Inventor
- FreeCAD

به Blender منتقل شود.

در حالت ایده‌آل، Add-on بتواند Hierarchy قطعات را حفظ کند.

مثلاً:

```text
Assembly
├── Housing
│   ├── Screw
│   └── Cover
│
├── Electronics
│   ├── PCB
│   └── Connector
│
└── Mechanical
    ├── Shaft
    ├── Bearing
    └── Gear
```

---

# 18. Constraint System آینده

در نسخه پیشرفته می‌توان سیستم Constraint اضافه کرد.

مثلاً:

```text
Mate
Align
Insert
Concentric
Distance
Angle
```

هدف:

```text
Part A
   +
Part B
   ↓
Constraint
   ↓
Correct Assembly Position
```

اما این بخش نباید در نسخه اول پیاده‌سازی شود.

---

# 19. Undo / Safety

تمام عملیات باید با Blender Undo سازگار باشند.

همچنین Add-on نباید:

- Mesh را تغییر دهد
- Material را تغییر دهد
- Object را حذف کند
- Origin را تغییر دهد

مگر اینکه کاربر صراحتاً درخواست کند.

تمرکز نسخه اول فقط:

```text
Transform
+
Animation
```

باشد.

---

# 20. نسخه‌بندی پیشنهادی

## Version 1.0

- Selected Objects
- Collection
- Save Assembly State
- Explode
- Assemble
- Reverse workflow
- Distance
- From Center
- World Axis
- Local Axis
- Start/End Frame
- Bezier/Linear/Sine
- Optional Rotation
- Clear Animation

## Version 1.5

- Auto Sequence
- Manual Sequence
- Per-object distance
- Staggered animation
- Better hierarchy support

## Version 2.0

- Assembly stages
- Constraint system
- CAD hierarchy support
- Exploded-view camera
- Technical drawing mode
- Product visualization presets

## Version 3.0

- CAD-aware assembly
- Automatic part relationships
- Smart constraints
- Advanced procedural exploded animations

---

# 21. معیار موفقیت نسخه اول

نسخه اول زمانی موفق است که کاربر بتواند:

1. یک Assembly را وارد Blender کند.
2. قطعات را در حالت assembled قرار دهد.
3. قطعات را انتخاب کند یا Collection را انتخاب کند.
4. روی `Set Assembly Position` کلیک کند.
5. مقدار Explode Distance را تعیین کند.
6. روی `Explode` کلیک کند.
7. Animation در Timeline ایجاد شود.
8. با Play، قطعات از هم جدا شوند.
9. روی `Assemble` کلیک کند.
10. قطعات دوباره دقیقاً به محل اولیه برگردند.

بدون اینکه مدل اصلی خراب شود.

---

# 22. فلسفه طراحی

این Add-on نباید صرفاً یک Script کوچک برای Explode کردن Objectها باشد.

هدف بلندمدت:

> تبدیل Blender به یک ابزار حرفه‌ای برای Product Assembly Visualization.

یعنی چیزی بین:

```text
CAD Assembly
      +
Blender Visualization
      +
Motion Graphics
      +
Technical Animation
```

با تمرکز ویژه روی محصولات مکانیکی و الکترونیکی.

---

# 23. نام پیشنهادی

نام فعلی:

**Exploded Assembly Studio**

نام‌های جایگزین:

- Assembly Motion
- Explode Studio
- AssemblyFX
- ExplodeKit
- Product Assembly Animator
- CAD Explode Studio
- Assembly Animator for Blender

پیشنهاد فعلی برای توسعه:

**Exploded Assembly Studio**

زیرا بعداً می‌تواند به یک ابزار بزرگ‌تر برای Product Visualization تبدیل شود.
