"""
==================
ModEM
==================

# Generate files for ModEM

# revised by JP 2017
# revised by AK 2017 to bring across functionality from ak branch

"""
from __future__ import print_function
import os
import sys
import numpy as np
from matplotlib import pyplot as plt
from scipy import stats as stats, interpolate as spi

from mtpy.modeling import ws3dinv as ws
from mtpy.utils import mesh_tools as mtmesh, gis_tools as gis_tools, filehandling as mtfh
from mtpy.utils.decorator import deprecated

from .exception import ModEMError

try:
    from evtk.hl import gridToVTK
except ImportError:
    print ('If you want to write a vtk file for 3d viewing, you need download '
           'and install evtk from https://bitbucket.org/pauloh/pyevtk')

__all__ = ['Model']


class Model(object):
    """
    make and read a FE mesh grid

    The mesh assumes the coordinate system where:
        x == North
        y == East
        z == + down

    All dimensions are in meters.

    The mesh is created by first making a regular grid around the station area,
    then padding cells are added that exponentially increase to the given
    extensions.  Depth cell increase on a log10 scale to the desired depth,
    then padding cells are added that increase exponentially.

    Arguments
    -------------
        **station_object** : mtpy.modeling.modem.Stations object
                            .. seealso:: mtpy.modeling.modem.Stations

    Examples
    -------------

    :Example 1 --> create mesh first then data file: ::

        >>> import mtpy.modeling.modem as modem
        >>> import os
        >>> # 1) make a list of all .edi files that will be inverted for
        >>> edi_path = r"/home/EDI_Files"
        >>> edi_list = [os.path.join(edi_path, edi)
                        for edi in os.listdir(edi_path)
        >>> ...         if edi.find('.edi') > 0]
        >>> # 2) Make a Stations object
        >>> stations_obj = modem.Stations()
        >>> stations_obj.get_station_locations_from_edi(edi_list)
        >>> # 3) make a grid from the stations themselves with 200m cell spacing
        >>> mmesh = modem.Model(station_obj)
        >>> # change cell sizes
        >>> mmesh.cell_size_east = 200,
        >>> mmesh.cell_size_north = 200
        >>> mmesh.ns_ext = 300000 # north-south extension
        >>> mmesh.ew_ext = 200000 # east-west extension of model
        >>> mmesh.make_mesh()
        >>> # check to see if the mesh is what you think it should be
        >>> msmesh.plot_mesh()
        >>> # all is good write the mesh file
        >>> msmesh.write_model_file(save_path=r"/home/modem/Inv1")
        >>> # create data file
        >>> md = modem.Data(edi_list, station_locations=mmesh.station_locations)
        >>> md.write_data_file(save_path=r"/home/modem/Inv1")

    :Example 2 --> Rotate Mesh: ::

        >>> mmesh.mesh_rotation_angle = 60
        >>> mmesh.make_mesh()

    .. note:: ModEM assumes all coordinates are relative to North and East, and
             does not accommodate mesh rotations, therefore, here the rotation
             is of the stations, which essentially does the same thing.  You
             will need to rotate you data to align with the 'new' coordinate
             system.

    ==================== ======================================================
    Attributes           Description
    ==================== ======================================================
    cell_size_east       mesh block width in east direction
                         *default* is 500
    cell_size_north      mesh block width in north direction
                         *default* is 500
    edi_list             list of .edi files to invert for
    grid_east            overall distance of grid nodes in east direction
    grid_north           overall distance of grid nodes in north direction
    grid_z               overall distance of grid nodes in z direction
    model_fn             full path to initial file name
    n_layers             total number of vertical layers in model
    nodes_east           relative distance between nodes in east direction
    nodes_north          relative distance between nodes in north direction
    nodes_z              relative distance between nodes in east direction
    pad_east             number of cells for padding on E and W sides
                         *default* is 7
    pad_north            number of cells for padding on S and N sides
                         *default* is 7
    pad_num              number of cells with cell_size with outside of
                         station area.  *default* is 3
    pad_method           method to use to create padding:
                         extent1, extent2 - calculate based on ew_ext and
                         ns_ext
                         stretch - calculate based on pad_stretch factors
    pad_stretch_h        multiplicative number for padding in horizontal
                         direction.
    pad_stretch_v        padding cells N & S will be pad_root_north**(x)
    pad_z                number of cells for padding at bottom
                         *default* is 4
    ew_ext               E-W extension of model in meters
    ns_ext               N-S extension of model in meters
    res_list             list of resistivity values for starting model
    res_model            starting resistivity model
    mesh_rotation_angle  Angle to rotate the grid to. Angle is measured
                         positve clockwise assuming North is 0 and east is 90.
                         *default* is None
    save_path            path to save file to
    station_fn           full path to station file
    station_locations    location of stations
    title                title in initial file
    z1_layer             first layer thickness
    z_bottom             absolute bottom of the model *default* is 300,000
    z_target_depth       Depth of deepest target, *default* is 50,000
    ==================== ======================================================


    ==================== ======================================================
    Methods              Description
    ==================== ======================================================
    make_mesh            makes a mesh from the given specifications
    plot_mesh            plots mesh to make sure everything is good
    write_initial_file   writes an initial model file that includes the mesh
    ==================== ======================================================
    """

    def __init__(self, station_object=None, **kwargs):
        self._logger = MtPyLog().get_mtpy_logger(self.__class__.__name__)
        self.station_locations = station_object

        # size of cells within station area in meters
        self.cell_size_east = 500
        self.cell_size_north = 500

        # padding cells on either side
        self.pad_east = 7
        self.pad_north = 7
        self.pad_z = 4

        self.pad_num = 3

        self.ew_ext = 100000
        self.ns_ext = 100000

        # root of padding cells
        self.pad_stretch_h = 1.2
        self.pad_stretch_v = 1.2

        # method to use to create padding
        self.pad_method = 'extent1'

        self.z1_layer = 10
        self.z_target_depth = 50000
        self.z_bottom = 300000

        # number of vertical layers
        self.n_layers = 30

        # strike angle to rotate grid to
        self.mesh_rotation_angle = 0

        # --> attributes to be calculated
        # grid nodes
        self._nodes_east = None
        self._nodes_north = None
        self._nodes_z = None

        # grid locations
        self.grid_east = None
        self.grid_north = None
        self.grid_z = None

        # resistivity model
        self.res_starting_value = 100.0
        self.res_model = None

        # inital file stuff
        self.model_fn = None
        self.save_path = os.getcwd()
        self.model_fn_basename = 'ModEM_Model_File.rho'
        if self.model_fn is not None:
            self.save_path = os.path.dirname(self.model_fn)
            self.model_fn_basename = os.path.basename(self.model_fn)

        self.title = 'Model File written by MTpy.modeling.modem'
        self.res_scale = 'loge'

        for key in kwargs.keys():
            setattr(self, key, kwargs[key])

    ### --> make nodes and grid symbiotic so if you set one the other one
    ###     gets set as well
    ## Nodes East
    @property
    def nodes_east(self):
        if self.grid_east is not None:
            self._nodes_east = np.array([abs(self.grid_east[ii + 1] - self.grid_east[ii])
                                         for ii in range(self.grid_east.size - 1)])
        return self._nodes_east

    @nodes_east.setter
    def nodes_east(self, nodes):
        nodes = np.array(nodes)
        self._nodes_east = nodes
        self.grid_east = np.array([-nodes.sum() / 2 + nodes[0:ii].sum()
                                   for ii in range(nodes.size)] + \
                                  [nodes.sum() / 2])

    ## Nodes North
    @property
    def nodes_north(self):
        if self.grid_north is not None:
            self._nodes_north = np.array([abs(self.grid_north[ii + 1] - self.grid_north[ii])
                                          for ii in range(self.grid_north.size - 1)])
        return self._nodes_north

    @nodes_north.setter
    def nodes_north(self, nodes):
        nodes = np.array(nodes)
        self._nodes_north = nodes
        self.grid_north = np.array([-nodes.sum() / 2 + nodes[0:ii].sum()
                                    for ii in range(nodes.size)] + \
                                   [nodes.sum() / 2])

    @property
    def nodes_z(self):
        if self.grid_z is not None:
            self._nodes_z = np.array([abs(self.grid_z[ii + 1] - self.grid_z[ii])
                                      for ii in range(self.grid_z.size - 1)])

            return self._nodes_z

    @nodes_z.setter
    def nodes_z(self, nodes):
        nodes = np.array(nodes)
        self._nodes_z = nodes
        self.grid_z = np.array([nodes[0:ii].sum() for ii in range(nodes.size)] + \
                               [nodes.sum()])

    def make_mesh(self):
        """
        create finite element mesh according to user-input parameters.

        The mesh is built by:
            1. Making a regular grid within the station area.
            2. Adding pad_num of cell_width cells outside of station area
            3. Adding padding cells to given extension and number of padding
               cells.
            4. Making vertical cells starting with z1_layer increasing
               logarithmically (base 10) to z_target_depth and num_layers.
            5. Add vertical padding cells to desired extension.
            6. Check to make sure none of the stations lie on a node.
               If they do then move the node by .02*cell_width

        """

        ## --> find the edges of the grid
        ## calculate the extra width of padding cells
        ## multiply by 1.5 because this is only for 1 side
        pad_width_east = self.pad_num * 1.5 * self.cell_size_east
        pad_width_north = self.pad_num * 1.5 * self.cell_size_north

        ## get the extremities
        west = self.station_locations.rel_east.min() - pad_width_east
        east = self.station_locations.rel_east.max() + pad_width_east
        south = self.station_locations.rel_north.min() - pad_width_north
        north = self.station_locations.rel_north.max() + pad_width_north

        # round the numbers so they are easier to read
        west = np.round(west, -2)
        east = np.round(east, -2)
        south = np.round(south, -2)
        north = np.round(north, -2)

        # -------make a grid around the stations from the parameters above------

        # adjust the edges so we have a whole number of cells
        add_ew = ((east - west) % self.cell_size_east) / 2.
        add_ns = ((north - south) % self.cell_size_north) / 2.

        # --> make the inner grid first
        inner_east = np.arange(west + add_ew - self.cell_size_east,
                               east - add_ew + 2 * self.cell_size_east,
                               self.cell_size_east)
        inner_north = np.arange(south + add_ns + self.cell_size_north,
                                north - add_ns + 2 * self.cell_size_north,
                                self.cell_size_north)

        ## compute padding cells
        if self.pad_method == 'extent1':
            padding_east = mtmesh.get_padding_cells(self.cell_size_east,
                                                    self.ew_ext / 2 - east,
                                                    self.pad_east,
                                                    self.pad_stretch_h)
            padding_north = mtmesh.get_padding_cells(self.cell_size_north,
                                                     self.ns_ext / 2 - north,
                                                     self.pad_north,
                                                     self.pad_stretch_h)
        elif self.pad_method == 'extent2':
            padding_east = mtmesh.get_padding_cells2(self.cell_size_east,
                                                     inner_east[-1],
                                                     self.ew_ext / 2.,
                                                     self.pad_east)
            padding_north = mtmesh.get_padding_cells2(self.cell_size_north,
                                                      inner_north[-1],
                                                      self.ns_ext / 2.,
                                                      self.pad_north)
        elif self.pad_method == 'stretch':
            padding_east = mtmesh.get_padding_from_stretch(self.cell_size_east,
                                                           self.pad_stretch_h,
                                                           self.pad_east)
            padding_north = mtmesh.get_padding_from_stretch(self.cell_size_north,
                                                            self.pad_stretch_h,
                                                            self.pad_north)

        # make the horizontal grid
        self.grid_east = np.append(np.append(-1 * padding_east[::-1] + inner_east.min(),
                                             inner_east),
                                   padding_east + inner_east.max())
        self.grid_north = np.append(np.append(-1 * padding_north[::-1] + inner_north.min(),
                                              inner_north),
                                    padding_north + inner_north.max())

        # --> need to make sure none of the stations lie on the nodes
        for s_east in sorted(self.station_locations.rel_east):
            try:
                node_index = np.where(abs(s_east - self.grid_east) <
                                      .02 * self.cell_size_east)[0][0]
                if s_east - self.grid_east[node_index] > 0:
                    self.grid_east[node_index] -= .02 * self.cell_size_east
                elif s_east - self.grid_east[node_index] < 0:
                    self.grid_east[node_index] += .02 * self.cell_size_east
            except IndexError:
                continue

        # --> need to make sure none of the stations lie on the nodes
        for s_north in sorted(self.station_locations.rel_north):
            try:
                node_index = np.where(abs(s_north - self.grid_north) <
                                      .02 * self.cell_size_north)[0][0]
                if s_north - self.grid_north[node_index] > 0:
                    self.grid_north[node_index] -= .02 * self.cell_size_north
                elif s_north - self.grid_north[node_index] < 0:
                    self.grid_north[node_index] += .02 * self.cell_size_north
            except IndexError:
                continue

        # --> make depth grid
        log_z = np.logspace(np.log10(self.z1_layer),
                            np.log10(self.z_target_depth - np.logspace(np.log10(self.z1_layer),
                                                                       np.log10(self.z_target_depth),
                                                                       num=self.n_layers)[-2]),
                            num=self.n_layers - self.pad_z)

        z_nodes = np.array([np.round(zz, -int(np.floor(np.log10(zz)) - 1)) for zz in
                            log_z])

        # padding cells in the vertical
        z_padding = mtmesh.get_padding_cells(z_nodes[-1],
                                             self.z_bottom - z_nodes.sum(),
                                             self.pad_z,
                                             self.pad_stretch_v)
        # make the blocks into nodes as oppose to total width
        z_padding = np.array([z_padding[ii + 1] - z_padding[ii]
                              for ii in range(z_padding.size - 1)])

        self.nodes_z = np.append(z_nodes, z_padding)

        # compute grid center
        center_east = np.round(self.grid_east.min() - self.grid_east.mean(), -1)
        center_north = np.round(self.grid_north.min() - self.grid_north.mean(), -1)
        center_z = 0

        # this is the value to the lower left corner from the center.
        self.grid_center = np.array([center_north, center_east, center_z])

        # --> print out useful information
        self.get_mesh_params()

    def get_mesh_params(self, file=sys.stdout):  # todo rename to print_mesh_params
        # --> print out useful information
        print('-' * 15, file=file)
        print('\tNumber of stations = {0}'.format(len(self.station_locations.station)), file=file)
        print('\tDimensions: ', file=file)
        print('\t\te-w = {0}'.format(self.grid_east.size), file=file)
        print('\t\tn-s = {0}'.format(self.grid_north.size), file=file)
        print('\t\tz  = {0} (without 7 air layers)'.format(self.grid_z.size), file=file)
        print('\tExtensions: ', file=file)
        print('\t\te-w = {0:.1f} (m)'.format(self.nodes_east.__abs__().sum()), file=file)
        print('\t\tn-s = {0:.1f} (m)'.format(self.nodes_north.__abs__().sum()), file=file)
        print('\t\t0-z = {0:.1f} (m)'.format(self.nodes_z.__abs__().sum()), file=file)

        print('\tStations rotated by: {0:.1f} deg clockwise positive from N'.format(self.mesh_rotation_angle), file=file)
        print('', file=file)
        print(' ** Note ModEM does not accommodate mesh rotations, it assumes', file=file)
        print('    all coordinates are aligned to geographic N, E', file=file)
        print('    therefore rotating the stations will have a similar effect', file=file)
        print('    as rotating the mesh.', file=file)
        print('-' * 15, file=file)

    def plot_mesh(self, east_limits=None, north_limits=None, z_limits=None,
                  **kwargs):
        """
        Plot the mesh to show model grid

        Arguments:
        ----------
            **east_limits** : tuple (xmin,xmax)
                             plot min and max distances in meters for the
                             E-W direction.  If None, the east_limits
                             will be set to furthest stations east and west.
                             *default* is None

            **north_limits** : tuple (ymin,ymax)
                             plot min and max distances in meters for the
                             N-S direction.  If None, the north_limits
                             will be set to furthest stations north and south.
                             *default* is None

            **z_limits** : tuple (zmin,zmax)
                            plot min and max distances in meters for the
                            vertical direction.  If None, the z_limits is
                            set to the number of layers.  Z is positive down
                            *default* is None
        """

        fig_size = kwargs.pop('fig_size', [6, 6])
        fig_dpi = kwargs.pop('fig_dpi', 300)
        fig_num = kwargs.pop('fig_num', 1)

        station_marker = kwargs.pop('station_marker', 'v')
        marker_color = kwargs.pop('station_color', 'b')
        marker_size = kwargs.pop('marker_size', 2)

        line_color = kwargs.pop('line_color', 'k')
        line_width = kwargs.pop('line_width', .5)

        plt.rcParams['figure.subplot.hspace'] = .3
        plt.rcParams['figure.subplot.wspace'] = .3
        plt.rcParams['figure.subplot.left'] = .12
        plt.rcParams['font.size'] = 7

        fig = plt.figure(fig_num, figsize=fig_size, dpi=fig_dpi)
        plt.clf()

        # make a rotation matrix to rotate data
        # cos_ang = np.cos(np.deg2rad(self.mesh_rotation_angle))
        # sin_ang = np.sin(np.deg2rad(self.mesh_rotation_angle))

        # turns out ModEM has not accomodated rotation of the grid, so for
        # now we will not rotate anything (angle=0.0)
        cos_ang = 1
        sin_ang = 0

        # --->plot map view
        ax1 = fig.add_subplot(1, 2, 1, aspect='equal')

        # plot station locations
        plot_east = self.station_locations.rel_east
        plot_north = self.station_locations.rel_north

        # plot stations
        ax1.scatter(plot_east,
                    plot_north,
                    marker=station_marker,
                    c=marker_color,
                    s=marker_size)

        east_line_xlist = []
        east_line_ylist = []
        north_min = self.grid_north.min()
        north_max = self.grid_north.max()
        for xx in self.grid_east:
            east_line_xlist.extend([xx * cos_ang + north_min * sin_ang,
                                    xx * cos_ang + north_max * sin_ang])
            east_line_xlist.append(None)
            east_line_ylist.extend([-xx * sin_ang + north_min * cos_ang,
                                    -xx * sin_ang + north_max * cos_ang])
            east_line_ylist.append(None)
        ax1.plot(east_line_xlist,
                 east_line_ylist,
                 lw=line_width,
                 color=line_color)

        north_line_xlist = []
        north_line_ylist = []
        east_max = self.grid_east.max()
        east_min = self.grid_east.min()
        for yy in self.grid_north:
            north_line_xlist.extend([east_min * cos_ang + yy * sin_ang,
                                     east_max * cos_ang + yy * sin_ang])
            north_line_xlist.append(None)
            north_line_ylist.extend([-east_min * sin_ang + yy * cos_ang,
                                     -east_max * sin_ang + yy * cos_ang])
            north_line_ylist.append(None)
        ax1.plot(north_line_xlist,
                 north_line_ylist,
                 lw=line_width,
                 color=line_color)

        if east_limits is None:
            ax1.set_xlim(plot_east.min() - 10 * self.cell_size_east,
                         plot_east.max() + 10 * self.cell_size_east)
        else:
            ax1.set_xlim(east_limits)

        if north_limits is None:
            ax1.set_ylim(plot_north.min() - 10 * self.cell_size_north,
                         plot_north.max() + 10 * self.cell_size_east)
        else:
            ax1.set_ylim(north_limits)

        ax1.set_ylabel('Northing (m)', fontdict={'size': 9, 'weight': 'bold'})
        ax1.set_xlabel('Easting (m)', fontdict={'size': 9, 'weight': 'bold'})

        # ---------------------------------------
        # plot depth view along the east direction
        ax2 = fig.add_subplot(1, 2, 2, aspect='auto', sharex=ax1)

        # plot the grid
        east_line_xlist = []
        east_line_ylist = []
        for xx in self.grid_east:
            east_line_xlist.extend([xx, xx])
            east_line_xlist.append(None)
            east_line_ylist.extend([0,
                                    self.grid_z.max()])
            east_line_ylist.append(None)
        ax2.plot(east_line_xlist,
                 east_line_ylist,
                 lw=line_width,
                 color=line_color)

        z_line_xlist = []
        z_line_ylist = []
        for zz in self.grid_z:
            z_line_xlist.extend([self.grid_east.min(),
                                 self.grid_east.max()])
            z_line_xlist.append(None)
            z_line_ylist.extend([zz, zz])
            z_line_ylist.append(None)
        ax2.plot(z_line_xlist,
                 z_line_ylist,
                 lw=line_width,
                 color=line_color)

        # --> plot stations
        ax2.scatter(plot_east,
                    [0] * self.station_locations.station.size,
                    marker=station_marker,
                    c=marker_color,
                    s=marker_size)

        if z_limits is None:
            ax2.set_ylim(self.z_target_depth, -200)
        else:
            ax2.set_ylim(z_limits)

        if east_limits is None:
            ax1.set_xlim(plot_east.min() - 10 * self.cell_size_east,
                         plot_east.max() + 10 * self.cell_size_east)
        else:
            ax1.set_xlim(east_limits)

        ax2.set_ylabel('Depth (m)', fontdict={'size': 9, 'weight': 'bold'})
        ax2.set_xlabel('Easting (m)', fontdict={'size': 9, 'weight': 'bold'})

        plt.show()

        return

    @deprecated("this is duplicated")  # todo merge this to the function plot_mesh()
    def plot_mesh_xy(self):
        """
        # add mesh grid lines in xy plan north-east map
        :return:
        """
        plt.figure(dpi=200)

        cos_ang = 1
        sin_ang = 0

        line_color = 'b'  # 'k'
        line_width = 0.5

        east_line_xlist = []
        east_line_ylist = []
        north_min = self.grid_north.min()
        north_max = self.grid_north.max()
        for xx in self.grid_east:
            east_line_xlist.extend([xx * cos_ang + north_min * sin_ang,
                                    xx * cos_ang + north_max * sin_ang])
            east_line_xlist.append(None)
            east_line_ylist.extend([-xx * sin_ang + north_min * cos_ang,
                                    -xx * sin_ang + north_max * cos_ang])
            east_line_ylist.append(None)

        plt.plot(east_line_xlist, east_line_ylist, lw=line_width, color=line_color)

        north_line_xlist = []
        north_line_ylist = []
        east_max = self.grid_east.max()
        east_min = self.grid_east.min()
        for yy in self.grid_north:
            north_line_xlist.extend([east_min * cos_ang + yy * sin_ang,
                                     east_max * cos_ang + yy * sin_ang])
            north_line_xlist.append(None)
            north_line_ylist.extend([-east_min * sin_ang + yy * cos_ang,
                                     -east_max * sin_ang + yy * cos_ang])
            north_line_ylist.append(None)

        plt.plot(north_line_xlist, north_line_ylist, lw=line_width, color=line_color)

        # if east_limits == None:
        #     ax1.set_xlim(plot_east.min() - 50 * self.cell_size_east,
        #                  plot_east.max() + 50 * self.cell_size_east)
        # else:
        #     ax1.set_xlim(east_limits)
        #
        # if north_limits == None:
        #     ax1.set_ylim(plot_north.min() - 50 * self.cell_size_north,
        #                  plot_north.max() + 50 * self.cell_size_north)
        # else:
        #     ax1.set_ylim(north_limits)

        plt.xlim(east_min, east_max)
        plt.ylim(north_min, north_max)

        plt.ylabel('Northing (m)', fontdict={'size': 9, 'weight': 'bold'})
        plt.xlabel('Easting (m)', fontdict={'size': 9, 'weight': 'bold'})
        plt.title("Mesh grid in north-east dimension")

        plt.show()

        return

    @deprecated("this is duplicated")  # todo merge this to the function plot_mesh()
    def plot_mesh_xz(self):
        """
        display the mesh in North-Depth aspect
        :return:
        """
        station_marker = 'v'
        marker_color = 'b'
        marker_size = 2

        line_color = 'b'
        line_width = 0.5

        # fig = plt.figure(2, dpi=200)
        fig = plt.figure(dpi=200)
        plt.clf()
        ax2 = plt.gca()
        # ---------------------------------------
        # plot depth view along the north direction
        # ax2 = fig.add_subplot(1, 2, 2, aspect='auto', sharex=ax1)

        # plot the grid
        east_line_xlist = []
        east_line_ylist = []
        for xx in self.grid_east:
            east_line_xlist.extend([xx, xx])
            east_line_xlist.append(None)
            east_line_ylist.extend([0,
                                    self.grid_z.max()])
            east_line_ylist.append(None)
        ax2.plot(east_line_xlist,
                 east_line_ylist,
                 lw=line_width,
                 color=line_color)

        z_line_xlist = []
        z_line_ylist = []
        for zz in self.grid_z:
            z_line_xlist.extend([self.grid_east.min(),
                                 self.grid_east.max()])
            z_line_xlist.append(None)
            z_line_ylist.extend([zz, zz])
            z_line_ylist.append(None)
        ax2.plot(z_line_xlist,
                 z_line_ylist,
                 lw=line_width,
                 color=line_color)

        # --> plot stations
        # ax2.scatter(plot_east, [0] * self.station_locations.shape[0],
        #            marker=station_marker, c=marker_color,s=marker_size)


        ax2.set_ylim(self.z_target_depth, -2000)

        #
        # if east_limits == None:
        #     ax2.set_xlim(plot_east.min() - 50 * self.cell_size_east,
        #                  plot_east.max() + 50 * self.cell_size_east)
        # else:
        #     ax2.set_xlim(east_limits)

        ax2.set_ylabel('Depth (m)', fontdict={'size': 9, 'weight': 'bold'})
        ax2.set_xlabel('Northing (m)', fontdict={'size': 9, 'weight': 'bold'})

        plt.show()

    def plot_topograph(self):
        """
        display topography elevation data together with station locations on a cell-index N-E map
        :return:
        """
        # fig_size = kwargs.pop('fig_size', [6, 6])
        # fig_dpi = kwargs.pop('fig_dpi', 300)
        # fig_num = kwargs.pop('fig_num', 1)
        #
        # station_marker = kwargs.pop('station_marker', 'v')
        # marker_color = kwargs.pop('station_color', 'b')
        # marker_size = kwargs.pop('marker_size', 2)
        #
        # line_color = kwargs.pop('line_color', 'k')
        # line_width = kwargs.pop('line_width', .5)
        #
        # plt.rcParams['figure.subplot.hspace'] = .3
        # plt.rcParams['figure.subplot.wspace'] = .3
        # plt.rcParams['figure.subplot.left'] = .12
        # plt.rcParams['font.size'] = 7

        # fig = plt.figure(3, dpi=200)
        fig = plt.figure(dpi=200)
        plt.clf()
        ax = plt.gca()

        # topography data image
        # plt.imshow(elev_mg) # this upside down
        # plt.imshow(elev_mg[::-1])  # this will be correct - water shadow flip of the image
        imgplot = plt.imshow(self.surface_dict['topography'],
                             origin='lower')  # the orgin is in the lower left corner SW.
        divider = make_axes_locatable(ax)
        # pad = separation from figure to colorbar
        cax = divider.append_axes("right", size="3%", pad=0.2)
        mycb = plt.colorbar(imgplot, cax=cax, use_gridspec=True)  # cmap=my_cmap_r, does not work!!
        mycb.outline.set_linewidth(2)
        mycb.set_label(label='Elevation (metre)', size=12)
        # make a rotation matrix to rotate data
        # cos_ang = np.cos(np.deg2rad(self.mesh_rotation_angle))
        # sin_ang = np.sin(np.deg2rad(self.mesh_rotation_angle))

        # turns out ModEM has not accomodated rotation of the grid, so for
        # now we will not rotate anything.
        # cos_ang = 1
        # sin_ang = 0

        # --->plot map view
        # ax1 = fig.add_subplot(1, 2, 1, aspect='equal')

        # plot station locations in grid

        sgindex_x = self.station_grid_index[0]
        sgindex_y = self.station_grid_index[1]

        self._logger.debug("station grid index x: %s", sgindex_x)
        self._logger.debug("station grid index y: %s", sgindex_y)

        ax.scatter(sgindex_x, sgindex_y, marker='v', c='b', s=2)

        ax.set_xlabel('Easting Cell Index', fontdict={'size': 9, 'weight': 'bold'})
        ax.set_ylabel('Northing Cell Index', fontdict={'size': 9, 'weight': 'bold'})
        ax.set_title("Elevation and Stations in N-E Map (Cells)")

        plt.show()

    def write_model_file(self, **kwargs):
        """
        will write an initial file for ModEM.

        Note that x is assumed to be S --> N, y is assumed to be W --> E and
        z is positive downwards.  This means that index [0, 0, 0] is the
        southwest corner of the first layer.  Therefore if you build a model
        by hand the layer block will look as it should in map view.

        Also, the xgrid, ygrid and zgrid are assumed to be the relative
        distance between neighboring nodes.  This is needed because wsinv3d
        builds the  model from the bottom SW corner assuming the cell width
        from the init file.



        Key Word Arguments:
        ----------------------

            **nodes_north** : np.array(nx)
                        block dimensions (m) in the N-S direction.
                        **Note** that the code reads the grid assuming that
                        index=0 is the southern most point.

            **nodes_east** : np.array(ny)
                        block dimensions (m) in the E-W direction.
                        **Note** that the code reads in the grid assuming that
                        index=0 is the western most point.

            **nodes_z** : np.array(nz)
                        block dimensions (m) in the vertical direction.
                        This is positive downwards.

            **save_path** : string
                          Path to where the initial file will be saved
                          to savepath/model_fn_basename

            **model_fn_basename** : string
                                    basename to save file to
                                    *default* is ModEM_Model.ws
                                    file is saved at savepath/model_fn_basename

            **title** : string
                        Title that goes into the first line
                        *default* is Model File written by MTpy.modeling.modem

            **res_model** : np.array((nx,ny,nz))
                        Prior resistivity model.

                        .. note:: again that the modeling code
                        assumes that the first row it reads in is the southern
                        most row and the first column it reads in is the
                        western most column.  Similarly, the first plane it
                        reads in is the Earth's surface.

            **res_starting_value** : float
                                     starting model resistivity value,
                                     assumes a half space in Ohm-m
                                     *default* is 100 Ohm-m

            **res_scale** : [ 'loge' | 'log' | 'log10' | 'linear' ]
                            scale of resistivity.  In the ModEM code it
                            converts everything to Loge,
                            *default* is 'loge'

        """
        for key in kwargs.keys():
            setattr(self, key, kwargs[key])

        if self.save_path is not None:
            self.model_fn = os.path.join(self.save_path,
                                         self.model_fn_basename)

        if self.model_fn is None:
            if self.save_path is None:
                self.save_path = os.getcwd()
                self.model_fn = os.path.join(self.save_path,
                                             self.model_fn_basename)
            elif os.path.isdir(self.save_path) == True:
                self.model_fn = os.path.join(self.save_path,
                                             self.model_fn_basename)
            else:
                self.save_path = os.path.dirname(self.save_path)
                self.model_fn = self.save_path

        # get resistivity model
        if self.res_model is None:
            self.res_model = np.zeros((self.nodes_north.size,
                                       self.nodes_east.size,
                                       self.nodes_z.size))
            self.res_model[:, :, :] = self.res_starting_value

        elif type(self.res_model) in [float, int]:
            self.res_starting_value = self.res_model
            self.res_model = np.zeros((self.nodes_north.size,
                                       self.nodes_east.size,
                                       self.nodes_z.size))
            self.res_model[:, :, :] = self.res_starting_value

        # --> write file
        ifid = file(self.model_fn, 'w')
        ifid.write('# {0}\n'.format(self.title.upper()))
        ifid.write('{0:>5}{1:>5}{2:>5}{3:>5} {4}\n'.format(self.nodes_north.size,
                                                           self.nodes_east.size,
                                                           self.nodes_z.size,
                                                           0,
                                                           self.res_scale.upper()))

        # write S --> N node block
        for ii, nnode in enumerate(self.nodes_north):
            ifid.write('{0:>12.3f}'.format(abs(nnode)))

        ifid.write('\n')

        # write W --> E node block
        for jj, enode in enumerate(self.nodes_east):
            ifid.write('{0:>12.3f}'.format(abs(enode)))
        ifid.write('\n')

        # write top --> bottom node block
        for kk, zz in enumerate(self.nodes_z):
            ifid.write('{0:>12.3f}'.format(abs(zz)))
        ifid.write('\n')

        # write the resistivity in log e format
        if self.res_scale.lower() == 'loge':
            write_res_model = np.log(self.res_model[::-1, :, :])
        elif self.res_scale.lower() == 'log' or \
                        self.res_scale.lower() == 'log10':
            write_res_model = np.log10(self.res_model[::-1, :, :])
        elif self.res_scale.lower() == 'linear':
            write_res_model = self.res_model[::-1, :, :]

        # write out the layers from resmodel
        for zz in range(self.nodes_z.size):
            ifid.write('\n')
            for ee in range(self.nodes_east.size):
                for nn in range(self.nodes_north.size):
                    ifid.write('{0:>13.5E}'.format(write_res_model[nn, ee, zz]))
                ifid.write('\n')

        if self.grid_center is None:
            # compute grid center
            center_east = -self.nodes_east.__abs__().sum() / 2
            center_north = -self.nodes_north.__abs__().sum() / 2
            center_z = 0
            self.grid_center = np.array([center_north, center_east, center_z])

        ifid.write('\n{0:>16.3f}{1:>16.3f}{2:>16.3f}\n'.format(self.grid_center[0],
                                                               self.grid_center[1], self.grid_center[2]))

        if self.mesh_rotation_angle is None:
            ifid.write('{0:>9.3f}\n'.format(0))
        else:
            ifid.write('{0:>9.3f}\n'.format(self.mesh_rotation_angle))
        ifid.close()

        print 'Wrote file to: {0}'.format(self.model_fn)

    def read_model_file(self, model_fn=None, shift_grid=False):
        """
        read an initial file and return the pertinent information including
        grid positions in coordinates relative to the center point (0,0) and
        starting model.

        Note that the way the model file is output, it seems is that the
        blocks are setup as

        ModEM:                           WS:
        ----------                      -----
        0-----> N_north                 0-------->N_east
        |                               |
        |                               |
        V                               V
        N_east                          N_north


        Arguments:
        ----------

            **model_fn** : full path to initializing file.

        Outputs:
        --------

            **nodes_north** : np.array(nx)
                        array of nodes in S --> N direction

            **nodes_east** : np.array(ny)
                        array of nodes in the W --> E direction

            **nodes_z** : np.array(nz)
                        array of nodes in vertical direction positive downwards

            **res_model** : dictionary
                        dictionary of the starting model with keys as layers

            **res_list** : list
                        list of resistivity values in the model

            **title** : string
                         title string

        """

        if model_fn is not None:
            self.model_fn = model_fn

        if self.model_fn is None:
            raise ModEMError('model_fn is None, input a model file name')

        if os.path.isfile(self.model_fn) is None:
            raise ModEMError('Cannot find {0}, check path'.format(self.model_fn))

        self.save_path = os.path.dirname(self.model_fn)

        ifid = file(self.model_fn, 'r')
        ilines = ifid.readlines()
        ifid.close()

        self.title = ilines[0].strip()

        # get size of dimensions, remembering that x is N-S, y is E-W, z is + down
        nsize = ilines[1].strip().split()
        n_north = int(nsize[0])
        n_east = int(nsize[1])
        n_z = int(nsize[2])
        log_yn = nsize[4]

        # get nodes
        self.nodes_north = np.array([np.float(nn)
                                     for nn in ilines[2].strip().split()])
        self.nodes_east = np.array([np.float(nn)
                                    for nn in ilines[3].strip().split()])
        self.nodes_z = np.array([np.float(nn)
                                 for nn in ilines[4].strip().split()])

        self.res_model = np.zeros((n_north, n_east, n_z))

        # get model
        count_z = 0
        line_index = 6
        count_e = 0
        while count_z < n_z:
            iline = ilines[line_index].strip().split()
            # blank lines spit the depth blocks, use those as a marker to
            # set the layer number and start a new block
            if len(iline) == 0:
                count_z += 1
                count_e = 0
                line_index += 1
            # each line in the block is a line of N-->S values for an east value
            else:
                north_line = np.array([float(nres) for nres in
                                       ilines[line_index].strip().split()])

                # Need to be sure that the resistivity array matches
                # with the grids, such that the first index is the
                # furthest south
                self.res_model[:, count_e, count_z] = north_line[::-1]

                count_e += 1
                line_index += 1

        # --> get grid center and rotation angle
        if len(ilines) > line_index:
            for iline in ilines[line_index:]:
                ilist = iline.strip().split()
                # grid center
                if len(ilist) == 3:
                    self.grid_center = np.array(ilist, dtype=np.float)
                # rotation angle
                elif len(ilist) == 1:
                    self.rotation_angle = np.float(ilist[0])
                else:
                    pass

        # --> make sure the resistivity units are in linear Ohm-m
        if log_yn.lower() == 'loge':
            self.res_model = np.e ** self.res_model
        elif log_yn.lower() == 'log' or log_yn.lower() == 'log10':
            self.res_model = 10 ** self.res_model

        # center the grids
        if self.grid_center is None:
            self.grid_center = np.array([-self.nodes_north.sum() / 2,
                                         -self.nodes_east.sum() / 2,
                                         0.0])

        # need to shift the grid if the center is not symmetric
        shift_north = self.grid_center[0] + self.nodes_north.sum() / 2
        shift_east = self.grid_center[1] + self.nodes_east.sum() / 2

        # shift the grid.  if shift is + then that means the center is
        self.grid_north += shift_north
        self.grid_east += shift_east

        # get cell size
        self.cell_size_east = stats.mode(self.nodes_east)[0][0]
        self.cell_size_north = stats.mode(self.nodes_north)[0][0]

        # get number of padding cells
        self.pad_east = np.where(self.nodes_east[0:int(self.nodes_east.size / 2)]
                                 != self.cell_size_east)[0][-1]
        self.north_pad = np.where(self.nodes_north[0:int(self.nodes_north.size / 2)]
                                  != self.cell_size_north)[0][-1]

    def read_ws_model_file(self, ws_model_fn):
        """
        reads in a WS3INV3D model file
        """

        ws_model_obj = ws.WSModel(ws_model_fn)
        ws_model_obj.read_model_file()

        # set similar attributes
        for ws_key in ws_model_obj.__dict__.keys():
            for md_key in self.__dict__.keys():
                if ws_key == md_key:
                    setattr(self, ws_key, ws_model_obj.__dict__[ws_key])

        # compute grid center
        center_east = -self.nodes_east.__abs__().sum() / 2
        center_north = -self.nodes_norths.__abs__().sum() / 2
        center_z = 0
        self.grid_center = np.array([center_north, center_east, center_z])

    def write_vtk_file(self, vtk_save_path=None,
                       vtk_fn_basename='ModEM_model_res'):
        """
        write a vtk file to view in Paraview or other

        Arguments:
        -------------
            **vtk_save_path** : string
                                directory to save vtk file to.
                                *default* is Model.save_path
            **vtk_fn_basename** : string
                                  filename basename of vtk file
                                  *default* is ModEM_model_res, evtk will add
                                  on the extension .vtr
        """

        if vtk_save_path is None:
            vtk_fn = os.path.join(self.save_path, vtk_fn_basename)
        else:
            vtk_fn = os.path.join(vtk_save_path, vtk_fn_basename)

        # use cellData, this makes the grid properly as grid is n+1
        gridToVTK(vtk_fn,
                  self.grid_north / 1000.,
                  self.grid_east / 1000.,
                  self.grid_z / 1000.,
                  cellData={'resistivity': self.res_model})

        print '-' * 50
        print '--> Wrote model file to {0}\n'.format(vtk_fn)
        print '=' * 26
        print '  model dimensions = {0}'.format(self.res_model.shape)
        print '     * north         {0}'.format(self.nodes_north.size)
        print '     * east          {0}'.format(self.nodes_east.size)
        print '     * depth         {0}'.format(self.nodes_z.size)
        print '=' * 26

    def get_parameters(self):
        """
        get important model parameters to write to a file for documentation
        later.


        """

        parameter_list = ['cell_size_east',
                          'cell_size_north',
                          'ew_ext',
                          'ns_ext',
                          'pad_east',
                          'pad_north',
                          'pad_z',
                          'pad_num',
                          'z1_layer',
                          'z_target_depth',
                          'z_bottom',
                          'mesh_rotation_angle',
                          'res_starting_value',
                          'save_path']

        parameter_dict = {}
        for parameter in parameter_list:
            key = 'model.{0}'.format(parameter)
            parameter_dict[key] = getattr(self, parameter)

        parameter_dict['model.size'] = self.res_model.shape

        return parameter_dict

    # --> read in ascii dem file
    def read_dem_ascii(self, ascii_fn, cell_size=500, model_center=(0, 0),
                       rot_90=0, dem_rotation_angle=0):
        """
        read in dem which is ascii format

        The ascii format is assumed to be:
        ncols         3601
        nrows         3601
        xllcorner     -119.00013888889
        yllcorner     36.999861111111
        cellsize      0.00027777777777778
        NODATA_value  -9999
        elevation data W --> E
        N
        |
        V
        S
        """
        dfid = file(ascii_fn, 'r')
        d_dict = {}
        for ii in range(6):
            dline = dfid.readline()
            dline = dline.strip().split()
            key = dline[0].strip().lower()
            value = float(dline[1].strip())
            d_dict[key] = value

        x0 = d_dict['xllcorner']
        y0 = d_dict['yllcorner']
        nx = int(d_dict['ncols'])
        ny = int(d_dict['nrows'])
        cs = d_dict['cellsize']

        # read in the elevation data
        elevation = np.zeros((nx, ny))

        for ii in range(1, int(ny) + 2):
            dline = dfid.readline()
            if len(str(dline)) > 1:
                # needs to be backwards because first line is the furthest north row.
                elevation[:, -ii] = np.array(dline.strip().split(' '), dtype='float')
            else:
                break

        dfid.close()

        # create lat and lon arrays from the dem fle
        lon = np.arange(x0, x0 + cs * (nx), cs)
        lat = np.arange(y0, y0 + cs * (ny), cs)

        # calculate the lower left and uper right corners of the grid in meters
        ll_en = gis_tools.project_point_ll2utm(lat[0], lon[0])
        ur_en = gis_tools.project_point_ll2utm(lat[-1], lon[-1])

        # estimate cell sizes for each dem measurement
        d_east = abs(ll_en[0] - ur_en[0]) / nx
        d_north = abs(ll_en[1] - ur_en[1]) / ny

        # calculate the number of new cells according to the given cell size
        # if the given cell size and cs are similar int could make the value 0,
        # hence the need to make it one if it is 0.
        num_cells = max([1, int(cell_size / np.mean([d_east, d_north]))])

        # make easting and northing arrays in meters corresponding to lat and lon
        east = np.arange(ll_en[0], ur_en[0], d_east)
        north = np.arange(ll_en[1], ur_en[1], d_north)

        # resample the data accordingly
        new_east = east[np.arange(0, east.size, num_cells)]
        new_north = north[np.arange(0, north.size, num_cells)]
        new_x, new_y = np.meshgrid(np.arange(0, east.size, num_cells),
                                   np.arange(0, north.size, num_cells),
                                   indexing='ij')
        elevation = elevation[new_x, new_y]
        # make any null values set to minimum elevation, could be dangerous
        elevation[np.where(elevation == -9999.0)] = elevation[np.where(elevation != -9999.0)].min()

        # estimate the shift of the DEM to relative model coordinates
        mid_east = np.where(new_east >= model_center[0])[0][0]
        mid_north = np.where(new_north >= model_center[1])[0][0]

        new_east -= new_east[mid_east]
        new_north -= new_north[mid_north]

        # need to rotate cause I think I wrote the dem backwards
        if rot_90 == 1 or rot_90 == 3:
            elevation = np.rot90(elevation, rot_90)

        else:
            elevation = np.rot90(elevation, rot_90)

        if dem_rotation_angle != 0.0:
            cos_ang = np.cos(np.deg2rad(dem_rotation_angle))
            sin_ang = np.sin(np.deg2rad(dem_rotation_angle))
            rot_matrix = np.matrix(np.array([[cos_ang, sin_ang],
                                             [-sin_ang, cos_ang]]))

            new_coords = np.dot(rot_matrix, np.array([new_east, new_north]))
            new_east = new_coords[0]
            new_north = new_coords[1]

        return new_east, new_north, elevation

    def interpolate_elevation(self, elev_east, elev_north, elevation,
                              model_east, model_north, pad=3,
                              elevation_max=None):
        """
        interpolate the elevation onto the model grid.

        Arguments:
        ---------------

            **elev_east** : np.ndarray(num_east_nodes)
                          easting grid for elevation model

            **elev_north** : np.ndarray(num_north_nodes)
                          northing grid for elevation model

            **elevation** : np.ndarray(num_east_nodes, num_north_nodes)
                         elevation model assumes x is east, y is north
                         Units are meters

            **model_east** : np.ndarray(num_east_nodes_model)
                         relative easting grid of resistivity model

            **model_north** : np.ndarray(num_north_nodes_model)
                         relative northin grid of resistivity model

            **pad** : int
                    number of cells to repeat elevation model by.  So for pad=3,
                    then the interpolated elevation model onto the resistivity
                    model grid will have the outer 3 cells will be repeats of
                    the adjacent cell.  This is to extend the elevation model
                    to the resistivity model cause most elevation models will
                    not cover the entire area.

            **elevation_max** : float
                                maximum value for elevation
                                *default* is None, which will use
                                elevation.max()

        Returns:
        --------------

            **interp_elev** : np.ndarray(num_north_nodes_model, num_east_nodes_model)
                            the elevation model interpolated onto the resistivity
                            model grid.

        """
        # set a maximum on the elevation, used to get rid of singular high
        # points in the model
        if type(elevation_max) in [float, int]:
            max_find = np.where(elevation > float(elevation_max))
            elevation[max_find] = elevation_max

        # need to line up the elevation with the model
        grid_east, grid_north = np.broadcast_arrays(elev_east[:, None],
                                                    elev_north[None, :])
        # interpolate onto the model grid
        interp_elev = spi.griddata((grid_east.ravel(), grid_north.ravel()),
                                   elevation.ravel(),
                                   (model_east[:, None],
                                    model_north[None, :]),
                                   method='linear',
                                   fill_value=elevation.mean())

        interp_elev[0:pad, pad:-pad] = interp_elev[pad, pad:-pad]
        interp_elev[-pad:, pad:-pad] = interp_elev[-pad - 1, pad:-pad]
        interp_elev[:, 0:pad] = interp_elev[:, pad].repeat(pad).reshape(
            interp_elev[:, 0:pad].shape)
        interp_elev[:, -pad:] = interp_elev[:, -pad - 1].repeat(pad).reshape(
            interp_elev[:, -pad:].shape)

        # transpose the modeled elevation to align with x=N, y=E
        interp_elev = interp_elev.T

        return interp_elev

    def make_elevation_model(self, interp_elev, model_nodes_z,
                             elevation_cell=30, pad=3, res_air=1e12,
                             fill_res=100, res_sea=0.3):
        """
        Take the elevation data of the interpolated elevation model and map that
        onto the resistivity model by adding elevation cells to the existing model.

        ..Note: that if there are large elevation gains, the elevation cell size
                might need to be increased.

        Arguments:
        -------------
            **interp_elev** : np.ndarray(num_nodes_north, num_nodes_east)
                            elevation model that has been interpolated onto the
                            resistivity model grid. Units are in meters.

            **model_nodes_z** : np.ndarray(num_z_nodes_of_model)
                              vertical nodes of the resistivity model without
                              topography.  Note these are the nodes given in
                              relative thickness, not the grid, which is total
                              depth.  Units are meters.

            **elevation_cell** : float
                               height of elevation cells to be added on.  These
                               are assumed to be the same at all elevations.
                               Units are in meters

            **pad** : int
                    number of cells to look for maximum and minimum elevation.
                    So if you only want elevations within the survey area,
                    set pad equal to the number of padding cells of the
                    resistivity model grid.

            **res_air** : float
                        resistivity of air.  Default is 1E12 Ohm-m

            **fill_res** : float
                         resistivity value of subsurface in Ohm-m.

        Returns:
        -------------
            **elevation_model** : np.ndarray(num_north_nodes, num_east_nodes,
                                           num_elev_nodes+num_z_nodes)
                             Model grid with elevation mapped onto it.
                             Where anything above the surface will be given the
                             value of res_air, everything else will be fill_res

            **new_nodes_z** : np.ndarray(num_z_nodes+num_elev_nodes)
                            a new array of vertical nodes, where any nodes smaller
                            than elevation_cell will be set to elevation_cell.
                            This can be input into a modem.Model object to
                            rewrite the model file.

        """

        # calculate the max elevation within survey area
        elev_max = interp_elev[pad:-pad, pad:-pad].max()

        # need to set sea level to 0 elevation
        elev_min = max([0, interp_elev[pad:-pad, pad:-pad].min()])

        # scale the interpolated elevations to fit within elev_max, elev_min
        interp_elev[np.where(interp_elev > elev_max)] = elev_max
        # interp_elev[np.where(interp_elev < elev_min)] = elev_min

        # calculate the number of elevation cells needed
        num_elev_cells = int((elev_max - elev_min) / elevation_cell)
        print 'Number of elevation cells: {0}'.format(num_elev_cells)

        # find sea level if it is there
        if elev_min < 0:
            sea_level_index = num_elev_cells - abs(int((elev_min) / elevation_cell)) - 1
        else:
            sea_level_index = num_elev_cells - 1

        print 'Sea level index is {0}'.format(sea_level_index)

        # make an array of just the elevation for the model
        # north is first index, east is second, vertical is third
        elevation_model = np.ones((interp_elev.shape[0],
                                   interp_elev.shape[1],
                                   num_elev_cells + model_nodes_z.shape[0]))

        elevation_model[:, :, :] = fill_res

        # fill in elevation model with air values.  Remeber Z is positive down, so
        # the top of the model is the highest point and index 0 is highest
        # elevation
        for nn in range(interp_elev.shape[0]):
            for ee in range(interp_elev.shape[1]):
                # need to test for ocean
                if interp_elev[nn, ee] < 0:
                    # fill in from bottom to sea level, then rest with air
                    elevation_model[nn, ee, 0:sea_level_index] = res_air
                    dz = sea_level_index + abs(int((interp_elev[nn, ee]) / elevation_cell)) + 1
                    elevation_model[nn, ee, sea_level_index:dz] = res_sea
                else:
                    dz = int((elev_max - interp_elev[nn, ee]) / elevation_cell)
                    elevation_model[nn, ee, 0:dz] = res_air

        # make new z nodes array
        new_nodes_z = np.append(np.repeat(elevation_cell, num_elev_cells),
                                model_nodes_z)

        new_nodes_z[np.where(new_nodes_z < elevation_cell)] = elevation_cell

        return elevation_model, new_nodes_z

    def add_topography_to_model(self, dem_ascii_fn, write_file=True,
                                model_center=(0, 0), rot_90=0,
                                dem_rotation_angle=0, cell_size=500,
                                elev_cell=30, pad=1, elev_max=None):
        """
        Add topography to an existing model from a dem in ascii format.

        The ascii format is assumed to be:
        ncols         3601
        nrows         3601
        xllcorner     -119.00013888889
        yllcorner     36.999861111111
        cellsize      0.00027777777777778
        NODATA_value  -9999
        elevation data W --> E
        N
        |
        V
        S

        Arguments
        -------------
            **dem_ascii_fn** : string
                             full path to ascii dem file

            **model_fn** : string
                         full path to existing ModEM model file

            **model_center** : (east, north) in meters
                             Sometimes the center of the DEM and the center of the
                             model don't line up.  Use this parameter to line
                             everything up properly.

            **rot_90** : [ 0 | 1 | 2 | 3 ]
                       rotate the elevation model by rot_90*90 degrees.  Sometimes
                       the elevation model is flipped depending on your coordinate
                       system.

            **dem_rotation_angle: float (degrees from North)
                                  rotation angle to rotate station locations

            **cell_size** : float (meters)
                          horizontal cell size of grid to interpolate elevation
                          onto.  This should be smaller or equal to the input
                          model cell size to be sure there is not spatial aliasing

            **elev_cell** : float (meters)
                          vertical size of each elevation cell.  This value should
                          be about 1/10th the smalles skin depth.

        Returns
        ---------------
            **new_model_fn** : string
                             full path to model file that contains topography

        """
        ### 1.) read in the dem and center it onto the resistivity model
        e_east, e_north, elevation = self.read_dem_ascii(dem_ascii_fn,
                                                         cell_size=cell_size,
                                                         model_center=model_center,
                                                         rot_90=rot_90,
                                                         dem_rotation_angle=dem_rotation_angle)

        ### 2.) interpolate the elevation model onto the model grid
        m_elev = self.interpolate_elevation(e_east, e_north, elevation,
                                            self.grid_east, self.grid_north,
                                            pad=pad, elevation_max=elev_max)

        m_elev[np.where(m_elev == -9999.0)] = m_elev[np.where(m_elev != -9999.0)].min()
        ### 3.) make a resistivity model that incoorporates topography
        mod_elev, elev_nodes_z = self.make_elevation_model(m_elev,
                                                           self.nodes_z,
                                                           elevation_cell=elev_cell)

        ### 4.) write new model file
        self.nodes_z = elev_nodes_z
        self.res_model = mod_elev

        if write_file == True:
            self.save_path = os.path.dirname(self.model_fn)
            self.write_model_file(model_fn_basename='{0}_topo.rho'.format(
                os.path.basename(self.model_fn)[0:-4]))

            return self.model_fn

    def assign_resistivity_from_surfacedata(self, surfacename, resistivity_value, where='above'):
        """
        assign resistivity value to all points above or below a surface
        requires the surface_dict attribute to exist and contain data for
        surface key (can get this information from ascii file using
        project_surface)

        **inputs**
        surfacename = name of surface (must correspond to key in surface_dict)
        resistivity_value = value to assign
        where = 'above' or 'below' - assign resistivity above or below the
                surface
        """

        # FZ: should ref-define the self.res_model if its shape has changed after topo air layer are added


        gcz = np.mean([self.grid_z[:-1], self.grid_z[1:]], axis=0)

        #        logger.debug("gcz is the cells centre coordinates: %s, %s", len(gcz), gcz)
        # convert to positive down, relative to the top of the grid
        surfacedata = - self.surface_dict[surfacename]
        # surfacedata = self.surface_dict[surfacename] - self.sea_level

        # define topography, so that we don't overwrite cells above topography
        # first check if topography exists
        if 'topography' in self.surface_dict.keys():
            # second, check topography isn't the surface we're trying to assign
            # resistivity for
            if surfacename == 'topography':
                # if it is, we need to define the upper limit as the highest point in the surface
                top = np.zeros_like(surfacedata) + np.amin(surfacedata) - 1.
            else:
                # if not, upper limit of resistivity assignment is the topography, note positive downwards
                top = -self.surface_dict['topography']
        # if no topography, use top of model
        else:
            top = self.grid_z[0] + np.zeros_like(surfacedata)

        # assign resistivity value
        for j in range(len(self.res_model)):
            for i in range(len(self.res_model[j])):
                if where == 'above':
                    # needs to be above the surface but below the top (as defined before)
                    ii = np.where((gcz <= surfacedata[j, i]) & (gcz > top[j, i]))[0]
                else:  # for below the surface
                    ii = np.where(gcz > surfacedata[j, i])[0]

                self.res_model[j, i, ii] = resistivity_value

                if surfacename == 'topography':
                    iisea = np.where((gcz <= surfacedata[j, i]) & (gcz > 0.))[0]
                    self.res_model[j, i, iisea] = 0.3
                print j, i, ii

    def interpolate_elevation2(self, surfacefile=None, surface=None, surfacename=None,
                               method='nearest'):
        """
        project a surface to the model grid and add resulting elevation data
        to a dictionary called surface_dict. Assumes the surface is in lat/long
        coordinates (wgs84)

        **returns**
        nothing returned, but surface data are added to surface_dict under
        the key given by surfacename.

        **inputs**
        choose to provide either surface_file (path to file) or surface (tuple).
        If both are provided then surface tuple takes priority.

        surface elevations are positive up, and relative to sea level.
        surface file format is:

        ncols         3601
        nrows         3601
        xllcorner     -119.00013888889 (longitude of lower left)
        yllcorner     36.999861111111  (latitude of lower left)
        cellsize      0.00027777777777778
        NODATA_value  -9999
        elevation data W --> E
        N
        |
        V
        S

        Alternatively, provide a tuple with:
        (lon,lat,elevation)
        where elevation is a 2D array (shape (ny,nx)) containing elevation
        points (order S -> N, W -> E)
        and lon, lat are either 1D arrays containing list of longitudes and
        latitudes (in the case of a regular grid) or 2D arrays with same shape
        as elevation array containing longitude and latitude of each point.

        other inputs:
        surfacename = name of surface for putting into dictionary
        surface_epsg = epsg number of input surface, default is 4326 for lat/lon(wgs84)
        method = interpolation method. Default is 'nearest', if model grid is
        dense compared to surface points then choose 'linear' or 'cubic'

        """
        # initialise a dictionary to contain the surfaces
        if not hasattr(self, 'surface_dict'):
            self.surface_dict = {}

        # read the surface data in from ascii if surface not provided
        if surface is None:
            surface = mtfh.read_surface_ascii(surfacefile)

        x, y, elev = surface

        # if lat/lon provided as a 1D list, convert to a 2d grid of points
        if len(x.shape) == 1:
            x, y = np.meshgrid(x, y)

        xs, ys, utm_zone = gis_tools.project_points_ll2utm(y, x,
                                                           epsg=self.station_locations.model_epsg,
                                                           utm_zone=self.station_locations.model_utm_zone
                                                           )

        # get centre position of model grid in real world coordinates
        x0, y0 = [np.median(
            self.station_locations.station_locations[dd] - self.station_locations.station_locations['rel_' + dd]) for dd
            in
            ['east', 'north']]

        # centre points of model grid in real world coordinates
        xg, yg = [np.mean([arr[1:], arr[:-1]], axis=0)
                  for arr in [self.grid_east + x0, self.grid_north + y0]]

        # elevation in model grid
        # first, get lat,lon points of surface grid
        points = np.vstack([arr.flatten() for arr in [xs, ys]]).T
        # corresponding surface elevation points
        values = elev.flatten()
        # xi, the model grid points to interpolate to
        xi = np.vstack([arr.flatten() for arr in np.meshgrid(xg, yg)]).T
        # elevation on the centre of the grid nodes
        elev_mg = spi.griddata(
            points, values, xi, method=method).reshape(len(yg), len(xg))

        print(" Elevation data type and shape  *** ", type(elev_mg), elev_mg.shape, len(yg), len(xg))
        # <type 'numpy.ndarray'>  (65, 92), 65 92: it's 2D image with cell index as pixels
        # np.savetxt('E:/tmp/elev_mg.txt', elev_mg, fmt='%10.5f')


        # get a name for surface
        if surfacename is None:
            if surfacefile is not None:
                surfacename = os.path.basename(surfacefile)
            else:
                ii = 1
                surfacename = 'surface%01i' % ii
                while surfacename in self.surface_dict.keys():
                    ii += 1
                    surfacename = 'surface%01i' % ii

        # add surface to a dictionary of surface elevation data
        self.surface_dict[surfacename] = elev_mg

        return

    def add_topography_to_model2(self, topographyfile=None, topographyarray=None, interp_method='nearest',
                                 air_resistivity=1e12, sea_resistivity=0.3, airlayer_cellsize=None):
        """
        if air_layers is non-zero, will add topo: read in topograph file, make a surface model.
        Call project_stations_on_topography in the end, which will re-write the .dat file.

        If n_airlayers is zero, then cannot add topo data, only bathymetry is needed.
        """
        # first, get surface data
        if topographyfile is not None:
            self.interpolate_elevation2(surfacefile=topographyfile,
                                        surfacename='topography',
                                        method=interp_method)
        if topographyarray is not None:
            self.surface_dict['topography'] = topographyarray

        if self.n_airlayers is None or self.n_airlayers == 0:
            print("No air layers specified, so will not add air/topography !!!")
            print("Only bathymetry will be added below according to the topofile: sea-water low resistivity!!!")


        elif self.n_airlayers > 0:  # FZ: new logic, add equal blocksize air layers on top of the simple flat-earth grid
            # build air layers based on the inner core area
            padE = self.pad_east
            padN = self.pad_north
            #            topo_core = self.surface_dict['topography'][padN:-padN,padE:-padE]
            gcx, gcy = [np.mean([arr[:-1], arr[1:]], axis=0) for arr in self.grid_east, self.grid_north]
            core_cells = mtmesh.get_station_buffer(gcx,
                                                   gcy,
                                                   self.station_locations.station_locations['rel_east'],
                                                   self.station_locations.station_locations['rel_north'],
                                                   buf=5 * (self.cell_size_east * 2 + self.cell_size_north ** 2) ** 0.5)
            topo_core = self.surface_dict['topography'][core_cells]

            # log increasing airlayers, in reversed order
            new_air_nodes = mtmesh.make_log_increasing_array(self.z1_layer,
                                                             topo_core.max() - topo_core.min(),
                                                             self.n_airlayers + 1,
                                                             increment_factor=0.999)[::-1]
            # sum to get grid cell locations
            new_airlayers = np.array([new_air_nodes[:ii].sum() for ii in range(len(new_air_nodes) + 1)])
            # round to nearest whole number and reverse the order
            new_airlayers = np.around(new_airlayers - topo_core.max())

            print("new_airlayers", new_airlayers)

            print("self.grid_z[0:2]", self.grid_z[0:2])

            # add new air layers, cut_off some tailing layers to preserve array size.
            #            self.grid_z = np.concatenate([new_airlayers, self.grid_z[self.n_airlayers+1:] - self.grid_z[self.n_airlayers] + new_airlayers[-1]], axis=0)
            self.grid_z = np.concatenate([new_airlayers[:-1], self.grid_z + new_airlayers[-1]], axis=0)

        # print(" NEW self.grid_z shape and values = ", self.grid_z.shape, self.grid_z)
        #            print self.grid_z

        # update the z-centre as the top air layer
        self.grid_center[2] = self.grid_z[0]

        # update the resistivity model
        new_res_model = np.ones((self.nodes_north.size,
                                 self.nodes_east.size,
                                 self.nodes_z.size)) * self.res_starting_value
        new_res_model[:, :, self.n_airlayers + 1:] = self.res_model
        self.res_model = new_res_model

        #        logger.info("begin to self.assign_resistivity_from_surfacedata(...)")
        self.assign_resistivity_from_surfacedata('topography', air_resistivity, where='above')

        ##        logger.info("begin to assign sea water resistivity")
        #        # first make a mask for all-land =1, which will be modified later according to air, water
        #        self.covariance_mask = np.ones_like(self.res_model)  # of grid size (xc, yc, zc)
        #
        #        # assign model areas below sea level but above topography, as seawater
        #        # get grid node centres
        #        gcz = np.mean([self.grid_z[:-1], self.grid_z[1:]], axis=0)
        #
        #        # convert topography to local grid coordinates
        #        topo = -self.surface_dict['topography']
        #        # assign values
        #        for j in range(len(self.res_model)):
        #            for i in range(len(self.res_model[j])):
        #                # assign all sites above the topography to air
        #                ii1 = np.where(gcz <= topo[j, i])[0]
        #                if len(ii1) > 0:
        #                    self.covariance_mask[j, i, ii1] = 0.
        #                # assign sea water to covariance and model res arrays
        #                ii = np.where(
        #                    np.all([gcz > 0., gcz <= topo[j, i]], axis=0))[0]
        #                if len(ii) > 0:
        #                    self.covariance_mask[j, i, ii] = 9.
        #                    self.res_model[j, i, ii] = sea_resistivity
        #                    print "assigning sea", j, i, ii
        #
        #        self.covariance_mask = self.covariance_mask[::-1]

        #        self.station_grid_index = self.project_stations_on_topography()

        #        logger.debug("NEW res_model and cov_mask shapes: %s, %s", self.res_model.shape, self.covariance_mask.shape)

        return


