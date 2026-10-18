"""Every GLSL source in shaders.py must compile in a real headless GL context.

test_shaders.py only checks that uniforms are declared; this test compiles each
vertex and fragment shader with moderngl so real GLSL errors are caught. It is
skipped with an explicit reason when moderngl or a headless context is missing.
"""
import unittest

import shaders

try:
    import moderngl
except ImportError:  # pragma: no cover - depends on the machine
    moderngl = None


def shader_sources():
    for name in sorted(dir(shaders)):
        value = getattr(shaders, name)
        if name.endswith(("_VS", "_FS")) and isinstance(value, str):
            yield name, value


@unittest.skipUnless(
    moderngl is not None,
    "moderngl is not installed: no headless context to compile shaders with",
)
class ShaderCompileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        errors = []
        for backend in ("egl", None, "glx"):
            try:
                kwargs = {"require": 330}
                if backend is not None:
                    kwargs["backend"] = backend
                cls.ctx = moderngl.create_standalone_context(**kwargs)
                return
            except Exception as exc:  # no EGL/GLX or no GL 3.3 on this machine
                errors.append(f"{backend or 'default'}: {exc}")
        raise unittest.SkipTest(
            "could not create a headless GL 3.3 context: " + "; ".join(errors)
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.release()

    def _compile(self, name, source):
        # moderngl has no standalone shader-compile call: attaching the source to
        # a program compiles it, and linking a single-stage program is valid.
        if name.endswith("_VS"):
            self.ctx.program(vertex_shader=source)
        else:
            self.ctx.program(fragment_shader=source)

    def test_shader_sources_are_found(self):
        self.assertGreater(len(list(shader_sources())), 10)

    def test_every_shader_compiles(self):
        problems = []
        for name, source in shader_sources():
            try:
                self._compile(name, source)
            except Exception as exc:
                problems.append(f"{name}: {exc}")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
