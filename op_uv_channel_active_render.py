import bpy

from .settings import tt_settings


class op(bpy.types.Operator):
	bl_idname = "uv.textools_uv_channel_active_render"
	bl_label = "Make UV Channel render default"
	bl_description = "Make the active UV channel the render default for all the selected Objects"
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		if not bpy.context.active_object:
			return False
		if bpy.context.active_object.type != 'MESH':
			return False
		if not bpy.context.object.data.uv_layers:
			return False
		return True

	def execute(self, context):
		index = int(tt_settings().uv_channel)
		for ob in [ob for ob in bpy.context.selected_objects if ob.type == 'MESH']:
			if index < len(ob.data.uv_layers):
				ob.data.uv_layers.active_index = index
				ob.data.uv_layers[index].active_render = True
		return {'FINISHED'}
