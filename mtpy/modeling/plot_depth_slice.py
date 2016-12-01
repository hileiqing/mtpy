# ==============================================================================
# plot depth slices
# ==============================================================================

import os

import matplotlib.colorbar as mcb
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize
from matplotlib.ticker import MultipleLocator
from mtpy.modeling.modem_new import Data
from mtpy.modeling.modem_new import Model

import mtpy.utils.exceptions as mtex
try:
    from evtk.hl import gridToVTK, pointsToVTK
except ImportError:
    print ('If you want to write a vtk file for 3d viewing, you need download '
           'and install evtk from https://bitbucket.org/pauloh/pyevtk')

    print ('Note: if you are using Windows you should build evtk first with'
           'either MinGW or cygwin using the command: \n'
           '    python setup.py build -compiler=mingw32  or \n'
           '    python setup.py build -compiler=cygwin')


class PlotDepthSlice(object):
    """
    Plots depth slices of resistivity model

    :Example: ::

        >>> import mtpy.modeling.ws3dinv as ws
        >>> mfn = r"/home/MT/ws3dinv/Inv1/Test_model.00"
        >>> sfn = r"/home/MT/ws3dinv/Inv1/WSStationLocations.txt"
        >>> # plot just first layer to check the formating
        >>> pds = ws.PlotDepthSlice(model_fn=mfn, station_fn=sfn,
        >>> ...                     depth_index=0, save_plots='n')
        >>> #move color bar up
        >>> pds.cb_location
        >>> (0.64500000000000002, 0.14999999999999997, 0.3, 0.025)
        >>> pds.cb_location = (.645, .175, .3, .025)
        >>> pds.redraw_plot()
        >>> #looks good now plot all depth slices and save them to a folder
        >>> pds.save_path = r"/home/MT/ws3dinv/Inv1/DepthSlices"
        >>> pds.depth_index = None
        >>> pds.save_plots = 'y'
        >>> pds.redraw_plot()

    ======================= ===================================================
    Attributes              Description
    ======================= ===================================================
    cb_location             location of color bar (x, y, width, height)
                            *default* is None, automatically locates
    cb_orientation          [ 'vertical' | 'horizontal' ]
                            *default* is horizontal
    cb_pad                  padding between axes and colorbar
                            *default* is None
    cb_shrink               percentage to shrink colorbar by
                            *default* is None
    climits                 (min, max) of resistivity color on log scale
                            *default* is (0, 4)
    cmap                    name of color map *default* is 'jet_r'
    data_fn                 full path to data file
    depth_index             integer value of depth slice index, shallowest
                            layer is 0
    dscale                  scaling parameter depending on map_scale
    ew_limits               (min, max) plot limits in e-w direction in
                            map_scale units. *default* is None, sets viewing
                            area to the station area
    fig_aspect              aspect ratio of plot. *default* is 1
    fig_dpi                 resolution of figure in dots-per-inch. *default* is
                            300
    fig_list                list of matplotlib.figure instances for each
                            depth slice
    fig_size                [width, height] in inches of figure size
                            *default* is [6, 6]
    font_size               size of ticklabel font in points, labels are
                            font_size+2. *default* is 7
    grid_east               relative location of grid nodes in e-w direction
                            in map_scale units
    grid_north              relative location of grid nodes in n-s direction
                            in map_scale units
    grid_z                  relative location of grid nodes in z direction
                            in map_scale units
    initial_fn              full path to initial file
    map_scale               [ 'km' | 'm' ] distance units of map. *default* is
                            km
    mesh_east               np.meshgrid(grid_east, grid_north, indexing='ij')
    mesh_north              np.meshgrid(grid_east, grid_north, indexing='ij')
    model_fn                full path to model file
    nodes_east              relative distance betwen nodes in e-w direction
                            in map_scale units
    nodes_north             relative distance betwen nodes in n-s direction
                            in map_scale units
    nodes_z                 relative distance betwen nodes in z direction
                            in map_scale units
    ns_limits               (min, max) plot limits in n-s direction in
                            map_scale units. *default* is None, sets viewing
                            area to the station area
    plot_grid               [ 'y' | 'n' ] 'y' to plot mesh grid lines.
                            *default* is 'n'
    plot_yn                 [ 'y' | 'n' ] 'y' to plot on instantiation
    res_model               np.ndarray(n_north, n_east, n_vertical) of
                            model resistivity values in linear scale
    save_path               path to save figures to
    save_plots              [ 'y' | 'n' ] 'y' to save depth slices to save_path
    station_east            location of stations in east direction in
                            map_scale units
    station_fn              full path to station locations file
    station_names           station names
    station_north           location of station in north direction in
                            map_scale units
    subplot_bottom          distance between axes and bottom of figure window
    subplot_left            distance between axes and left of figure window
    subplot_right           distance between axes and right of figure window
    subplot_top             distance between axes and top of figure window
    title                   titiel of plot *default* is depth of slice
    xminorticks             location of xminorticks
    yminorticks             location of yminorticks
    ======================= ===================================================
    """

    def __init__(self, model_fn=None, data_fn=None, **kwargs):
        self.model_fn = model_fn
        self.data_fn = data_fn

        self.save_path = kwargs.pop('save_path', None)
        if self.model_fn is not None and self.save_path is None:
            self.save_path = os.path.dirname(self.model_fn)
        elif self.initial_fn is not None and self.save_path is None:
            self.save_path = os.path.dirname(self.initial_fn)

        if self.save_path is not None:
            if not os.path.exists(self.save_path):
                os.mkdir(self.save_path)

        self.save_plots = kwargs.pop('save_plots', 'y')

        self.depth_index = kwargs.pop('depth_index', None)
        self.map_scale = kwargs.pop('map_scale', 'km')
        # make map scale
        if self.map_scale == 'km':
            self.dscale = 1000.
        elif self.map_scale == 'm':
            self.dscale = 1.
        self.ew_limits = kwargs.pop('ew_limits', None)
        self.ns_limits = kwargs.pop('ns_limits', None)

        self.plot_grid = kwargs.pop('plot_grid', 'n')

        self.fig_size = kwargs.pop('fig_size', [6, 6])
        self.fig_dpi = kwargs.pop('dpi', 300)
        self.fig_aspect = kwargs.pop('fig_aspect', 1)
        self.title = kwargs.pop('title', 'on')
        self.fig_list = []

        self.xminorticks = kwargs.pop('xminorticks', 10000)
        self.yminorticks = kwargs.pop('yminorticks', 10000)

        self.climits = kwargs.pop('climits', (0, 4))
        self.cmap = kwargs.pop('cmap', 'jet_r')
        self.font_size = kwargs.pop('font_size', 8)

        self.cb_shrink = kwargs.pop('cb_shrink', .8)
        self.cb_pad = kwargs.pop('cb_pad', .01)
        self.cb_orientation = kwargs.pop('cb_orientation', 'horizontal') #'vertical')
        self.cb_location = kwargs.pop('cb_location', None)

        self.subplot_right = .99
        self.subplot_left = .085
        self.subplot_top = .92
        self.subplot_bottom = .1

        self.res_model = None
        self.grid_east = None
        self.grid_north = None
        self.grid_z = None

        self.nodes_east = None
        self.nodes_north = None
        self.nodes_z = None

        self.mesh_east = None
        self.mesh_north = None

        self.station_east = None
        self.station_north = None
        self.station_names = None

        self.plot_yn = kwargs.pop('plot_yn', 'n')
        if self.plot_yn == 'y':
            self.plot()

    def read_files(self):
        """
        read in the files to get appropriate information
        """
        # --> read in model file
        if self.model_fn is not None:
            if os.path.isfile(self.model_fn) == True:
                md_model = Model()
                md_model.read_model_file(self.model_fn)
                self.res_model = md_model.res_model
                self.grid_east = md_model.grid_east / self.dscale
                self.grid_north = md_model.grid_north / self.dscale
                self.grid_z = md_model.grid_z / self.dscale
                self.nodes_east = md_model.nodes_east / self.dscale
                self.nodes_north = md_model.nodes_north / self.dscale
                self.nodes_z = md_model.nodes_z / self.dscale
            else:
                raise mtex.MTpyError_file_handling(
                    '{0} does not exist, check path'.format(self.model_fn))

        # --> read in data file to get station locations
        if self.data_fn is not None:
            if os.path.isfile(self.data_fn) == True:
                md_data = Data()
                md_data.read_data_file(self.data_fn)
                self.station_east = md_data.station_locations['rel_east'] / self.dscale
                self.station_north = md_data.station_locations['rel_north'] / self.dscale
                self.station_names = md_data.station_locations['station']
            else:
                print 'Could not find data file {0}'.format(self.data_fn)

    def plot(self):
        """
        plot depth slices
        """
        # --> get information from files
        self.read_files()

        fdict = {'size': self.font_size + 2, 'weight': 'bold'}

        cblabeldict = {-2: '$10^{-3}$', -1: '$10^{-1}$', 0: '$10^{0}$', 1: '$10^{1}$',
                       2: '$10^{2}$', 3: '$10^{3}$', 4: '$10^{4}$', 5: '$10^{5}$',
                       6: '$10^{6}$', 7: '$10^{7}$', 8: '$10^{8}$'}

        # create an list of depth slices to plot
        print self.grid_z  #FZ:
        if self.depth_index == None:
            zrange = range(self.grid_z.shape[0])
        elif type(self.depth_index) is int:
            zrange = [self.depth_index]
        elif type(self.depth_index) is list or \
                        type(self.depth_index) is np.ndarray:
            zrange = self.depth_index

        print (zrange)

        # set the limits of the plot
        if self.ew_limits == None:
            if self.station_east is not None:
                xlimits = (np.floor(self.station_east.min()),
                           np.ceil(self.station_east.max()))
            else:
                xlimits = (self.grid_east[5], self.grid_east[-5])
        else:
            xlimits = self.ew_limits

        if self.ns_limits == None:
            if self.station_north is not None:
                ylimits = (np.floor(self.station_north.min()),
                           np.ceil(self.station_north.max()))
            else:
                ylimits = (self.grid_north[5], self.grid_north[-5])
        else:
            ylimits = self.ns_limits

        # make a mesh grid of north and east
        try:
            self.mesh_east, self.mesh_north = np.meshgrid(self.grid_east,
                                                          self.grid_north,
                                                          indexing='ij')
        except:
            self.mesh_east, self.mesh_north = [arr.T for arr in np.meshgrid(self.grid_east,
                                                                            self.grid_north)]

        plt.rcParams['font.size'] = self.font_size

        # --> plot depths into individual figures
        for ii in zrange:
            depth = '{0:.3f} ({1})'.format(self.grid_z[ii],
                                           self.map_scale)
            fig = plt.figure(depth, figsize=self.fig_size, dpi=self.fig_dpi)
            plt.clf()
            ax1 = fig.add_subplot(1, 1, 1, aspect=self.fig_aspect)
            plot_res = np.log10(self.res_model[:, :, ii].T)
            mesh_plot = ax1.pcolormesh(self.mesh_east,
                                       self.mesh_north,
                                       plot_res,
                                       cmap=self.cmap,
                                       vmin=self.climits[0],
                                       vmax=self.climits[1])

            # plot the stations
            if self.station_east is not None:
                for ee, nn in zip(self.station_east, self.station_north):
                    ax1.text(ee, nn, '*',
                             verticalalignment='center',
                             horizontalalignment='center',
                             fontdict={'size': 5, 'weight': 'bold'})

            # set axis properties
            ax1.set_xlim(xlimits)
            ax1.set_ylim(ylimits)
            ax1.xaxis.set_minor_locator(MultipleLocator(self.xminorticks / self.dscale))
            ax1.yaxis.set_minor_locator(MultipleLocator(self.yminorticks / self.dscale))
            ax1.set_ylabel('Northing (' + self.map_scale + ')', fontdict=fdict)
            ax1.set_xlabel('Easting (' + self.map_scale + ')', fontdict=fdict)
            ax1.set_title('Depth = {0}'.format(depth), fontdict=fdict)

            # plot the grid if desired
            if self.plot_grid == 'y':
                east_line_xlist = []
                east_line_ylist = []
                for xx in self.grid_east:
                    east_line_xlist.extend([xx, xx])
                    east_line_xlist.append(None)
                    east_line_ylist.extend([self.grid_north.min(),
                                            self.grid_north.max()])
                    east_line_ylist.append(None)
                ax1.plot(east_line_xlist,
                         east_line_ylist,
                         lw=.25,
                         color='k')

                north_line_xlist = []
                north_line_ylist = []
                for yy in self.grid_north:
                    north_line_xlist.extend([self.grid_east.min(),
                                             self.grid_east.max()])
                    north_line_xlist.append(None)
                    north_line_ylist.extend([yy, yy])
                    north_line_ylist.append(None)
                ax1.plot(north_line_xlist,
                         north_line_ylist,
                         lw=.25,
                         color='k')

            #FZ: fix miss-placed colorbar
            from mpl_toolkits.axes_grid1 import make_axes_locatable
            ax = plt.gca()

            # create an axes on the right side of ax. The width of cax will be 5%
            # of ax and the padding between cax and ax will be fixed at 0.05 inch.
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="5%", pad=0.05)

            mycb= plt.colorbar(mesh_plot, cax=cax, label='Resistivity ($\Omega \cdot$m)')
            #cax.set_label('Resistivity ($\Omega \cdot$m)') #,fontdict={'size': self.font_size + 1})

            # # plot the colorbar - Original
            # if self.cb_location is None:
            #     if self.cb_orientation == 'horizontal':
            #         self.cb_location = (ax1.axes.figbox.bounds[3] - .225,
            #                             ax1.axes.figbox.bounds[1] + .05, .3, .025)
            #
            #     elif self.cb_orientation == 'vertical':
            #         self.cb_location = ((ax1.axes.figbox.bounds[2] - .15,
            #                              ax1.axes.figbox.bounds[3] - .21, .025, .3))
            #
            # ax2 = fig.add_axes(self.cb_location)
            #
            # cb = mcb.ColorbarBase(ax2,
            #                       cmap=self.cmap,
            #                       norm=Normalize(vmin=self.climits[0],
            #                                      vmax=self.climits[1]),
            #                       orientation=self.cb_orientation)
            #
            # if self.cb_orientation == 'horizontal':
            #     cb.ax.xaxis.set_label_position('top')
            #     cb.ax.xaxis.set_label_coords(.5, 1.3)
            #
            #
            # elif self.cb_orientation == 'vertical':
            #     cb.ax.yaxis.set_label_position('right')
            #     cb.ax.yaxis.set_label_coords(1.25, .5)
            #     cb.ax.yaxis.tick_left()
            #     cb.ax.tick_params(axis='y', direction='in')
            #
            # cb.set_label('Resistivity ($\Omega \cdot$m)',
            #              fontdict={'size': self.font_size + 1})
            # cb.set_ticks(np.arange(self.climits[0], self.climits[1] + 1))
            # cb.set_ticklabels([cblabeldict[cc]
            #                    for cc in np.arange(self.climits[0],
            #                                        self.climits[1] + 1)])
            # plot the colorbar - Original-End
###FZ:  fig_list not work?
            self.fig_list.append(fig)

            # Figure Objects
            print(self.fig_list)

            # --> save plots to a common folder
            if self.save_plots == 'y':
                out_file_name= "Depth_{}_{:.4f}.png".format(ii, self.grid_z[ii])
                path2outfile=os.path.join(self.save_path, out_file_name)
                fig.savefig(path2outfile, dpi=self.fig_dpi, bbox_inches='tight')
            else:
                pass

# when runs interactively, plt show a figure
            plt.show()
            fig.clear()
            plt.close()

            return

    def redraw_plot(self):
        """
        redraw plot if parameters were changed

        use this function if you updated some attributes and want to re-plot.

        :Example: ::

            >>> # change the color and marker of the xy components
            >>> import mtpy.modeling.occam2d as occam2d
            >>> ocd = occam2d.Occam2DData(r"/home/occam2d/Data.dat")
            >>> p1 = ocd.plotAllResponses()
            >>> #change line width
            >>> p1.lw = 2
            >>> p1.redraw_plot()
        """
        for fig in self.fig_list:
            plt.close(fig)
        self.plot()

    def update_plot(self, fig):
        """
        update any parameters that where changed using the built-in draw from
        canvas.

        Use this if you change an of the .fig or axes properties

        :Example: ::

            >>> # to change the grid lines to only be on the major ticks
            >>> import mtpy.modeling.occam2d as occam2d
            >>> dfn = r"/home/occam2d/Inv1/data.dat"
            >>> ocd = occam2d.Occam2DData(dfn)
            >>> ps1 = ocd.plotAllResponses()
            >>> [ax.grid(True, which='major') for ax in [ps1.axrte,ps1.axtep]]
            >>> ps1.update_plot()

        """

        fig.canvas.draw()

    def __str__(self):
        """
        rewrite the string builtin to give a useful message
        """

        return ("Plots depth slices of model from WS3DINV")
