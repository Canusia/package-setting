"""Settings sidebar item (cis.menu_registry); the 120 of the ce menu.

On a cis without the registry nothing registers.
"""
try:
    from cis.menu_registry import menu
except ImportError:   # cis without the registry: the menu migrations still apply
    menu = None

if menu is not None:
    menu.register('ce', 'settings', 'Settings', url='setting:records',
                  icon='fas fa-fw fa-cog', order=120)
