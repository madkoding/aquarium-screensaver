# Third-party notices

## AMD FidelityFX Super Resolution 1.0

`fsr.py` is a GLSL port of the EASU and RCAS passes from AMD's FidelityFX Super
Resolution 1.0 (`ffx_fsr1.h` / `ffx_a.h`, v1.20210629), available at
<https://github.com/GPUOpen-Effects/FidelityFX-FSR> under the MIT license.

```
FidelityFX Super Resolution Sample

Copyright (c) 2021 Advanced Micro Devices, Inc. All rights reserved.
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files(the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and / or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions :
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

Changes made in the port: scalar 32-bit path only; `textureGather` is replaced
by `texelFetch` so it runs on OpenGL 3.3; clamp-to-edge is done by hand; small
epsilons guard divisions by zero in RCAS; an optional dither is added at the end.

## Libraries bundled in the `.scr`

The released `.scr` is a PyInstaller bundle. It includes these third-party
components, each under its own license (see each project for the full text):

| Component | License |
|---|---|
| Python (CPython) | PSF License |
| pygame-ce and SDL2 | LGPL-2.1 (pygame-ce), zlib (SDL2) |
| NumPy | BSD-3-Clause |
| moderngl and glcontext | MIT |
| Tcl/Tk (settings window) | Tcl/Tk license (BSD-style) |
| PyInstaller bootloader | GPL-2.0-or-later with a bootloader exception |

All of them are compatible with distributing this project under the GPL-3.0.
The complete source code of this project is in this repository.
