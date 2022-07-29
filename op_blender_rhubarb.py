from distutils.util import execute
import enum
from operator import index
import bpy
from bpy import types
from bpy.props import IntProperty, FloatProperty
import blf
import bgl
import io
import sys
import select
import subprocess
from threading import Thread, local
from queue import Queue, Empty
import json
import os


class RhubarbLipsyncOperator(bpy.types.Operator):
    """Run Rhubarb lipsync"""

    bl_idname = "object.rhubarb_lipsync"
    bl_label = "Rhubarb lipsync"

    cue_prefix = "Mouth_"
    hold_frame_threshold = 4

    def get_the_target(self, context):
        sc = context.scene
        obj = context.object
        prop = context.object.rhubarb
        if prop.obj_modes == "bone":
            bone = sc.bone_selection
            target = obj.pose.bones[f"{bone}"]
            return target
        if prop.obj_modes == "timeoffset":
            target = obj.grease_pencil_modifiers
            return target
        else:
            target = context.object
            return target

    def get_pose_dest(self, context, frame_num, set_pose):
        obj = context.object
        prop_name = context.object.rhubarb.presets
        target = self.get_the_target(context)
        prop = context.object.rhubarb
        if prop.obj_modes != "timeoffset":
            target["{0}".format(prop_name)] = set_pose
            self.set_keyframes(context, frame_num - self.hold_frame_threshold)
        else:
            set_pose = target[f"{prop_name}"].offset = set_pose
            self.set_keyframes(context, frame_num - self.hold_frame_threshold)

    def modal(self, context, event):
        wm = context.window_manager
        wm.progress_update(50)
        try:
            (stdout, stderr) = self.rhubarb.communicate(timeout=1)

            try:
                result = json.loads(stderr)
                if result["type"] == "progress":
                    print(result["log"]["message"])
                    self.message = result["log"]["message"]

                if result["type"] == "failure":
                    self.report(type={"ERROR Type Failure"}, message=result["reason"])
                    return {"CANCELLED"}

            except ValueError:
                pass
            except TypeError:
                pass
            except json.decoder.JSONDecodeError:
                pass

            self.rhubarb.poll()

            if self.rhubarb.returncode is not None:
                wm.event_timer_remove(self._timer)
                results = json.loads(stdout)
                fps = context.scene.render.fps
                obj = context.object
                last_frame = 0
                prev_pose = 0

                # Logic for Armature or GPencil obj
                for cue in results["mouthCues"]:
                    frame_num = round(cue["start"] * fps) + obj.rhubarb.start_frame
                    if frame_num - last_frame > self.hold_frame_threshold:
                        print(
                            "hold frame: {0}".format(
                                frame_num - self.hold_frame_threshold
                            )
                        )
                        # Set prev_pose for Armature or GPencil obj
                        self.get_pose_dest(context, frame_num, prev_pose)

                    print(
                        "start: {0} frame: {1} value: {2}".format(
                            cue["start"], frame_num, cue["value"]
                        )
                    )

                    mouth_shape = "mouth_" + cue["value"].lower()
                    if mouth_shape in context.object.rhubarb:
                        pose_index = context.object.rhubarb[mouth_shape]
                        print(pose_index)
                    else:
                        pose_index = 0
                        print(pose_index)

                    # Set pose_index for Armature or GPencil obj
                    self.get_pose_dest(context, frame_num, pose_index)
                    prev_pose = pose_index
                    last_frame = frame_num

                    wm.progress_end()
                return {"FINISHED"}

            return {"PASS_THROUGH"}
        except subprocess.TimeoutExpired as ex:
            return {"PASS_THROUGH"}
        except json.decoder.JSONDecodeError:
            print(stdout)
            print("Error!!! Json Decoder")
            wm.progress_end()
            return {"CANCELLED"}
        except Exception as ex:
            template = "An exception of type {0} occurred. Arguments:\n{1!r}"
            print(template.format(type(ex).__name__, ex.args))
            wm.progress_end()
            return {"CANCELLED"}

    def set_keyframes(self, context, frame):
        sc = context.scene
        obj = context.object
        prop = context.object.rhubarb
        prop_name = context.object.rhubarb.presets

        # Set target to Armature or GPencil obj
        if prop.obj_modes == "bone":
            bone = sc.bone_selection
            target = obj.pose.bones["{0}".format(bone)]
            key_name = f'["{prop_name}"]'
        if prop.obj_modes == "timeoffset":
            target = obj.grease_pencil_modifiers[f"{prop_name}"]
            key_name = "offset"
        if prop.obj_modes == "obj":
            target = obj
            key_name = f'["{prop_name}"]'

        # Keyframe target
        target.keyframe_insert(
            data_path=key_name,
            frame=frame,
        )
        context.object.animation_data.action.fcurves[-1].keyframe_points[
            -1
        ].interpolation = "CONSTANT"

    def invoke(self, context, event):
        preferences = context.preferences
        addon_prefs = preferences.addons[__package__].preferences

        inputfile = bpy.path.abspath(context.object.rhubarb.sound_file)
        dialogfile = bpy.path.abspath(context.object.rhubarb.dialog_file)
        recognizer = bpy.path.abspath(addon_prefs.recognizer)
        executable = bpy.path.abspath(addon_prefs.executable_path)
        # This is ugly, but Blender unpacks the zip without execute permission
        os.chmod(executable, 0o744)

        # Lines that need to be excuted before the modal operator can go below this comment.

        command = [
            executable,
            "-f",
            "json",
            "--machineReadable",
            "--extendedShapes",
            "GHX",
            "-r",
            recognizer,
            inputfile,
        ]

        if dialogfile:
            command.append("--dialogFile")
            command.append(dialogfile)

        self.rhubarb = subprocess.Popen(
            command, stdout=subprocess.PIPE, universal_newlines=True
        )

        wm = context.window_manager
        self._timer = wm.event_timer_add(2, window=context.window)

        wm.modal_handler_add(self)

        wm.progress_begin(0, 100)

        return {"RUNNING_MODAL"}

    def execute(self, context):
        return self.invoke(context, None)

    def finished(self, context):
        context.scene.frame_set(context.scene.frame_current + 1)
        wm = context.window_manager
        wm.event_timer_remove(self._timer)

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)


def register():
    bpy.utils.register_class(RhubarbLipsyncOperator)


def unregister():
    bpy.utils.unregister_class(RhubarbLipsyncOperator)


if __name__ == "__main__":
    register()
