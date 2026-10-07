import bpy

from .services import color_assign_service



class op(bpy.types.Operator):
	bl_idname = "uv.textools_color_convert_to_vertex_colors"
	bl_label = "Pack Texture"
	bl_description = "Pack ID Colors into single texture and UVs"
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context):
		if bpy.context.area.ui_type != 'UV':
			return False
		if not bpy.context.active_object:
			return False
		if bpy.context.active_object not in bpy.context.selected_objects:
			return False
		if len(bpy.context.selected_objects) != 1:
			return False
		if bpy.context.active_object.type != 'MESH':
			return False
		return True


	def execute(self, context):
		convert_vertex_colors(self, context)
		return {'FINISHED'}



def convert_vertex_colors(self, context):
	obj = bpy.context.active_object
	color_assign_service.convert_materials_to_vertex_colors(obj)

	# Back to object mode
	bpy.ops.object.mode_set(mode='VERTEX_PAINT')
	bpy.context.object.data.use_paint_mask = False

	# Switch Properties Tab
	for area in bpy.context.screen.areas:
		if area.type == 'PROPERTIES':
			for space in area.spaces:
				if space.type == 'PROPERTIES':
					space.context = 'DATA'

	# Switch textured shading
	for area in bpy.context.screen.areas:
		if area.type == 'VIEW_3D':
			for space in area.spaces:
				if space.type == 'VIEW_3D':
					space.shading.type = 'SOLID'

	# Clear materials?
	#bpy.ops.uv.textools_color_clear()

	bpy.ops.ui.textools_popup('INVOKE_DEFAULT', message="Vertex colors assigned")
