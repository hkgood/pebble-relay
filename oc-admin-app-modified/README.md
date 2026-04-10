# Modified oc-admin-app Files

This directory contains the modified files for oc-admin-app.

## Files Modified:
1. `lib/presentation/pages/home_page.dart` - Complete rewrite with new tab structure and AddInstanceBottomSheet

## Changes made:

### home_page.dart:
1. **Tab "概览" renamed to "虾厂"**
2. **Removed "实例" tab** - instances are now shown directly in 虾厂 tab
3. **FAB (floating action button) moved to "虾厂" tab**
4. **FAB opens a bottom sheet with two tabs:**
   - **快速添加** (default): Instructions for watchclaw plugin + copy token + OpenClaw binding prompt
   - **手动添加**: Existing manual instance adding form

### Key Features of Quick Add Tab:
- Step-by-step instructions with numbered cards
- One-click token copy button
- Ready-to-send OpenClaw binding prompt with token pre-filled
- Clean, modern UI matching existing style

## How to Apply:

1. First, clone/pull the latest oc-admin-app:
```bash
cd ~/oc-admin-app && git pull origin main
```

2. Copy the modified home_page.dart:
```bash
cp ~/.openclaw/workspace/oc-admin-app-modified/lib/presentation/pages/home_page.dart ~/oc-admin-app/lib/presentation/pages/home_page.dart
```

3. No changes needed to add_instance_page.dart - it's used as-is for the manual add tab

4. Run the app to test:
```bash
cd ~/oc-admin-app && flutter run
```

## File Location:
```
/Users/liuyilin/.openclaw/workspace/oc-admin-app-modified/lib/presentation/pages/home_page.dart
```
