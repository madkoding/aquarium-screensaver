"""Every uniform a shader uses must be declared in that same shader stage.

Runs without a GL context: it only reads the GLSL source strings in shaders.py.
"""
import re
import unittest

import shaders

DECLARATION = re.compile(
    r"^\s*uniform\s+(?:(?:lowp|mediump|highp)\s+)?\w+\s+(\w+)\s*(?:\[\s*\d+\s*\])?\s*;", re.M)
USE = re.compile(r"\bu_\w+\b")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"//[^\n]*")


def shader_sources():
    for name in sorted(dir(shaders)):
        value = getattr(shaders, name)
        if name.endswith(("_VS", "_FS")) and isinstance(value, str):
            yield name, value


def undeclared_uniforms(source):
    code = LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", source))
    return sorted(set(USE.findall(code)) - set(DECLARATION.findall(code)))


class ShaderUniformDeclarationTest(unittest.TestCase):
    def test_shader_sources_are_found(self):
        self.assertGreater(len(list(shader_sources())), 10)

    def test_every_used_uniform_is_declared(self):
        problems = []
        for name, source in shader_sources():
            missing = undeclared_uniforms(source)
            if missing:
                problems.append(f"{name}: {', '.join(missing)}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_checker_flags_undeclared_uniform(self):
        source = "uniform float u_time;\nvoid main() { gl_FragColor = vec4(u_time + u_irid); }"
        self.assertEqual(undeclared_uniforms(source), ["u_irid"])

    def test_checker_ignores_commented_uniform(self):
        source = "// uniform float u_irid;\nvoid main() { gl_FragColor = vec4(1.0); }"
        self.assertEqual(undeclared_uniforms(source), [])


if __name__ == "__main__":
    unittest.main()
