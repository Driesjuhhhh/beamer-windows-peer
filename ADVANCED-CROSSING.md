# Advanced Crossing (Windows Peer 1.4.5)

Install this fork version on **both** paired Windows PCs. Open **Crossing → Ways in → Advanced mode**. This replaces the simple Ways in controls with an editor for every active monitor of the two PCs.

1. Wait for both screen inventories. Blue tiles belong to this PC; green tiles belong to the other PC. Each tile has a number and Windows display-device name.
2. Click **Identify** to show numbers on every screen for five seconds. Select one tile first to identify just that screen, including a screen on the other PC.
3. Drag the screen tiles to match their physical arrangement. Nearby edges snap together. Different screen heights and staggered arrangements are supported.
4. Click **Apply layout**. Screens must not overlap and at least one edge must touch a screen of the other PC. The saved arrangement is also sent to the other PC with the device ownership reversed.
5. Push through a touching edge. Only its overlapping stretch crosses, and the pointer lands on the corresponding monitor at the matching height or width. Every touching pair can form its own crossing; gaps remain walls.

**Refresh screens** rereads Windows display geometry; screen inventories are also exchanged every three seconds over the existing authenticated encrypted link. **Reset layout** prepares the default side-by-side arrangement; Apply is still required to save it. Turning Advanced mode off restores the existing Ways in configuration on both connected PCs.

This is a Beamer arrangement, not a Windows monitor-settings editor. Arrange monitors of a single PC in Windows Display Settings as usual. Beamer does not create a portal across an internal Windows monitor edge; it crosses only an exposed physical edge. Only active monitors of the two paired Windows PCs are supported. This does not add a third PC or a Mac display editor. The simple Mac↔Windows mode retains its existing behavior.

Use Identify and the regular switch shortcut to recover if the arrangement is wrong. Hotkeys still follow the existing shortcut settings. Physical multi-PC testing, mixed-DPI hardware testing, and installing the MSI have not yet been verified; geometry, the editor, authenticated controls and targeted arrivals have automated coverage.
