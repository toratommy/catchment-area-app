import streamlit as st
import folium
from geopy.geocoders import Nominatim
import pandas as pd
import requests
import geopandas as gpd
import numpy as np
from census import Census
from scipy import *
import plotly.figure_factory as ff
import osmnx as ox
from folium.plugins import HeatMap
from folium.raster_layers import WmsTileLayer
from shapely.geometry import mapping
from folium.plugins import Fullscreen

def update_map_layer(session_state):
    # Update the tile layer based on user selection without resetting the existing overlays
    if session_state.tile_layer_type == 'WMS':
        session_state.tile_layer_value.add_to(session_state.catchment_map)
        if "bounds" in session_state:
            session_state.catchment_map.fit_bounds(st.session_state.bounds)
    else:
        session_state.catchment_map = folium.Map(location=[session_state.location.latitude, session_state.location.longitude], tiles=session_state.tile_layer_value, zoom_start=13)
        if "bounds" in session_state:
            session_state.catchment_map.fit_bounds(st.session_state.bounds)


def map_tile_layer_selections():
    tile_layer_dict = {"OpenStreetMap":"OpenStreetMap",
                       "CartoDB Positron":"CartoDB Positron", 
                       "CartoDB Voyager":"CartoDB Voyager", 
                       "CartoDB Dark Matter":"CartoDB Dark Matter", 
                       "ESRI Imagery":WmsTileLayer(url='http://services.arcgisonline.com/arcgis/rest/services/World_Imagery'+ '/MapServer/tile/{z}/{y}/{x}',
                                                   layers=None,
                                                   name='ESRI Imagery',
                                                   attr='ESRI World Imagery')
    }
    tile_layer_input = st.selectbox("Select Map Layer", 
                                    list(tile_layer_dict.keys()), 
                                    index=0)
    tile_layer_value = tile_layer_dict[tile_layer_input]
    if tile_layer_input == tile_layer_value:
        tile_layer_type = 'Base'
    else:
        tile_layer_type = 'WMS'
    return tile_layer_value, tile_layer_type

@st.experimental_fragment
def make_catchment_area_selections():
    """
    Display widgets to collect user inputs for generating a catchment area.

    Returns
    -------
    tuple
        A tuple containing the entered address as a string, the selected radius type as a string,
        and the specified radius as an integer.
    """
    address = st.text_input("Enter the Address", 
                            value='1 N Halsted St, Chicago, IL 60661')
    radius_type = st.selectbox("Enter Radius Type", 
                               ["Distance (miles)", "Travel time (minutes)"], 
                               index = 1)
    if radius_type ==  'Travel time (minutes)':
        travel_profile = st.selectbox("Select Travel Profile",
                                      ["Driving (car)","Driving (heavy goods vehicle)","Walking","Cycling (regular)","Cycling (road)","Cycling (mountain)","Cycling (electric)","Hiking","Wheelchair"])
        max_radius = 60
    else:
        travel_profile = None
        max_radius = 250
    radius = st.number_input(f"Enter Radius {radius_type.split()[-1]}", 
                             min_value=1, 
                             max_value=max_radius, 
                             value=10,
                             help="The max supported travel time radius is 60 minutes. Please set radius type to `Distance (miles)` if you wish to generate a larger area.")
    return address, radius_type, travel_profile, radius

@st.experimental_fragment
def make_census_variable_selections(filters_dict):
    """
    Display widgets to select demographic variables for data enrichment.

    Parameters
    ----------
    filters_dict : dict
        A dictionary with demographic variable groups as keys and lists of variable names as values.

    Returns
    -------
    tuple
        A tuple containing the selected variable group as a string, the selected variable name as a string,
        and the normalization preference as a string.
    """
    var_group = st.selectbox('Choose Census Variable Group', options=(v for v in filters_dict.keys()),index=445)
    var_name = st.selectbox('Choose Census Variable Name', options=filters_dict[var_group])
    normalization = st.radio("Normalize by Population?",["No", "Yes"],index=0)
    return var_group, var_name, normalization

@st.experimental_fragment
def make_poi_selections(osm_tags):
    """
    Display widgets for selecting POI categories and mapping preferences.

    Parameters
    ----------
    osm_tags: dictionary
        A dictionary of POI groups and assocaited categories to choose from.

    Returns
    -------
    tuple
        A tuple containing the list of selected POI group/categories as a dictionary, and the chosen map type as a string.
    """
    poi_group = st.selectbox('Select POI group',list(osm_tags.keys()))
    poi_categories = st.multiselect('Select POI categories',osm_tags[poi_group])
    poi_map_type = st.radio('Choose map type', ['POI markers','Heatmap (POI density)'])
    return {poi_group: poi_categories}, poi_map_type

def geocode_address(address):
    """
    Geocodes an address to a latitude and longitude.
    
    Parameters
    ----------
    address : str
        The address to geocode.
    
    Returns
    -------
    geopy.location.Location or None
        The location object for the address or None if geocoding fails.
    """
    geolocator = Nominatim(user_agent="catchment_area_explorer")
    try:
        return geolocator.geocode(address)
    except:
        return None

def plot_catchment_area(session_state):
    """
    plots an area based on drive time from a specified location.
    
    Parameters
    ----------
    session_state : session_state
        The current session state object.
    
    Returns
    -------
    shapely.geometry.Polygon
        The polygon representing the drive time area.
    """

    polygon = folium.GeoJson(session_state.catchment_area.geometry, style_function=lambda x:{'fillColor': 'blue', 'color': 'blue'})
    polygon.add_to(st.session_state.catchment_map)

    st.session_state.bounds = polygon.get_bounds()
    st.session_state.catchment_map.fit_bounds(st.session_state.bounds)

@st.cache_data    
def fetch_census_variables(api_url):
    """
    Fetches census variables from the U.S. Census API.
    
    Parameters
    ----------
    api_url : str
        The base URL for the Census API endpoint.
    
    Returns
    -------
    pandas.DataFrame or None
        A DataFrame containing the census variables and metadata, or None if the fetch fails.
    """
    variables_url = f"{api_url}/variables.json"
    try:
        response = requests.get(variables_url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        variables_dict = response.json()
        variables_df = pd.concat({k: pd.DataFrame(v).T for k, v in variables_dict.items()}, axis=0)
        variables_df = variables_df[variables_df['label'].str.contains('Estimate')].reset_index()
        variables_df.rename(columns={'level_1':'variable','concept':'Variable Group','label':'Variable Name'}, inplace=True)
        variables_df['Variable Name'] = variables_df['Variable Name'].str.replace('Estimate!!', '').str.replace('!!', ' ')

        # Determine variable type based on the 'Variable Name'
        variables_df['variable_type'] = variables_df['Variable Name'].apply(
            lambda x: 'population_count' if x.startswith('Total:') else 'other_metric'
        )

        return variables_df
    except requests.RequestException as e:
        print(f"Failed to fetch variables.json: {e}")
        return None
  
def load_state_boundaries(census_year):
    """
    Loads state boundaries using the US Census Bureau's cartographic boundary files for a given year.
    
    Parameters
    ----------
    census_year : str
        The census year for which to load state boundaries.
    
    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame containing the state boundaries.
    """
    url = "https://www2.census.gov/geo/tiger/GENZ{0}/shp/cb_{0}_us_state_20m.zip".format(census_year)
    gdf = gpd.read_file(url)
    return gdf

def find_intersecting_states(user_gdf, states_gdf):
    """
    Identifies states that intersect with a user-defined geography.
    
    Parameters
    ----------
    user_gdf : geopandas.GeoDataFrame
        The user-defined geography.
    states_gdf : geopandas.GeoDataFrame
        The GeoDataFrame containing state boundaries.
    
    Returns
    -------
    pandas.Series
        The GEOID of states that intersect with the user-defined geography.
    """
    intersecting_states = states_gdf[states_gdf.intersects(user_gdf.unary_union)]
    return intersecting_states['GEOID']

def load_tract_shapefile(state_code, census_year):
    """
    Loads a census tract shapefile from the Census website for a given state code and year.
    
    Parameters
    ----------
    state_code : str
        The state code for which to load the census tract shapefile.
    census_year : str
        The year of the census.
    
    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame containing the census tract shapefile data.
    """
    url = f"https://www2.census.gov/geo/tiger/TIGER{census_year}/TRACT/tl_{census_year}_{state_code}_tract.zip"
    gdf = gpd.read_file(url)
    return gdf

import geopandas as gpd

def calculate_overlapping_tracts(user_gdf, state_codes, census_year):
    """
    Calculates which tracts overlap with the user-defined geography for intersecting states
    and updates tract geometries to the intersection with the user-defined geography.
    Additionally, calculates the percentage of each tract area that is contained within the catchment.

    Parameters
    ----------
    user_gdf : geopandas.GeoDataFrame
        The user-defined geography.
    state_codes : list of str
        The state codes of the intersecting states.
    census_year : str
        The year of the census data.

    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame of overlapping tracts with updated geometries to the intersection areas
        and a new column indicating the percentage of the original tract covered by the intersection.
    """
    overlapping_tracts = gpd.GeoDataFrame()
    for state_code in state_codes:
        tract_gdf = load_tract_shapefile(state_code, census_year)

        # Calculate the intersection of each tract with the user-defined geography
        tract_gdf['intersection'] = tract_gdf.geometry.apply(lambda x: x.intersection(user_gdf.unary_union))

        # Calculate the percentage of the tract area contained within the catchment
        tract_gdf['coverage_percentage'] = tract_gdf.apply(lambda row: (row['intersection'].area / row['geometry'].area), axis=1)
        
        # Update the geometry to the intersection
        tract_gdf['geometry'] = tract_gdf['intersection']
        
        # Keep only tracts that have a non-empty intersection and at least some land area
        tract_gdf = tract_gdf[(~tract_gdf.geometry.is_empty) & (tract_gdf['ALAND']>0)]
        
        # Drop the temporary 'intersection' column as it's no longer needed
        tract_gdf = tract_gdf.drop(columns=['intersection'])

        overlapping_tracts = pd.concat([overlapping_tracts, tract_gdf], ignore_index=True)

    return overlapping_tracts


def fetch_census_data_for_tracts(census_api, census_year, variable_dict, overlapping_tracts, normalization):
    """
    Fetches census data for tracts within overlapping tracts dataframe, scaling data for 'population_count' variables 
    by the 'coverage_percentage'.
    
    Parameters
    ----------
    census_api : census.Census
        The Census API client.
    census_year : str
        The year of the census.
    variable_dict : dictionary
        A dictionary containing the variable codes and assocaited variable types.
    overlapping_tracts : geopandas.GeoDataFrame
        The GeoDataFrame of overlapping tracts.
    normalization : str
        Indicates if the data should be normalized.
    
    Returns
    -------
    pandas.DataFrame
        A DataFrame containing the fetched census data.
    """
    census_data_full = pd.DataFrame()

    # Group the overlapping tracts by state and county for batch fetching
    for (state_code, county_code), group in overlapping_tracts.groupby(['STATEFP', 'COUNTYFP']):
        # Fetch census data for all tracts within this state and county
        if normalization == 'Yes':
            fetch_vars = list(variable_dict.keys())+['B01003_001E'] # add population variable which will be used for normalization
        else:
            fetch_vars = list(variable_dict.keys())
        
        census_json = census_api.acs5.state_county_tract(fetch_vars, state_code, county_code, Census.ALL, year=census_year)
        # Convert the fetched data into a DataFrame
        census_data = pd.DataFrame(census_json)
        
        # Convert GEOID to a format that matches the overlapping_tracts for comparison
        census_data['GEOID'] = census_data.apply(lambda row: f"{row['state']}{row['county']}{row['tract']}", axis=1)
        
        # Filter the data to only include those tracts that are in the overlapping_tracts DataFrame
        census_data = census_data.merge(overlapping_tracts[['GEOID','coverage_percentage']], left_on='GEOID', right_on='GEOID', how='inner')

        # Scale the data for variables of type 'population_count' by 'coverage_percentage'
        for var, vtype in variable_dict.items():
            if vtype == 'population_count':
                census_data[var] = census_data[var] * census_data['coverage_percentage']

        if normalization == 'Yes':
            # scale total population by 'coverage_percentage'
            census_data['B01003_001E'] = census_data['B01003_001E'] * census_data['coverage_percentage']
            census_data['population_normalized'] = census_data[list(variable_dict)[0]]/census_data['B01003_001E']

        # Append the filtered data to the all_census_data DataFrame
        census_data_full = pd.concat([census_data_full, census_data], ignore_index=True)

    return census_data_full

def plot_census_data_on_map(session_state, census_variable, var_name, normalization):
    """
    Plots census data on a map, coloring tracts by a specified census variable.
    
    Parameters
    ----------
    session_state : st.session_state
        The current session state data.
    census_variable : str
        The census variable to color the tracts by.
    var_name : str
        The name of the variable (for display purposes).
    normalization : str
        Indicates if the data should be normalized.
    
    Returns
    -------
    None
    """
    # Initialize Census Map using user-selected map layer
    map_center = [session_state.catchment_area.geometry.centroid.y, session_state.catchment_area.geometry.centroid.x]
    m = folium.Map(location=map_center, tiles=None)
    # Handle both regular and WMS tile layers
    if session_state.tile_layer_type == 'WMS':
        session_state.tile_layer_value.add_to(m)
    else:
        m = folium.Map(location=[session_state.location.latitude, session_state.location.longitude], tiles=session_state.tile_layer_value, zoom_start=13)

    Fullscreen(position="topright", title="Expand me", title_cancel="Exit me", force_separate_button=True).add_to(m)
    folium.GeoJson(mapping(session_state.catchment_area.geometry), style_function=lambda x: {'color': 'blue', 'fill': False}).add_to(m)
    
    # Existing code for merging data and adding GeoJson layer
    merged_data = session_state.catchment_area.census_tracts.merge(session_state.catchment_area.census_data, left_on='GEOID', right_on='GEOID')
    geojson_data = merged_data.to_json()

    if normalization == 'Yes':
        plot_var = 'population_normalized'
        alias = var_name+' (Population Normalized):'
        deciles = merged_data['population_normalized'].quantile([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]).to_list()
    else:
        plot_var = census_variable
        alias = var_name+':'
        deciles = merged_data[census_variable].quantile([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]).to_list()

    folium.GeoJson(
        geojson_data,
        style_function=lambda feature: {
            'fillColor': get_color(feature['properties'][plot_var], deciles),
            'color': 'black',
            'weight': 0.1,
            'fillOpacity': 0.7,
        },
        tooltip=folium.GeoJsonTooltip(fields=[plot_var],
                                      aliases=[alias],
                                      localize=True)
    ).add_to(m)
    m.fit_bounds(session_state.bounds)
    return m

    
def get_color(value, deciles):
    """
    Determines the color for a value based on which decile it falls into.
    
    Parameters
    ----------
    value : float
       The value to be colored.
    deciles : list of float
        The decile thresholds for coloring.
    
    Returns
    -------
    str
        The color code for the given value based on its decile.
    """
    colors = ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c',
              '#fc4e2a', '#e31a1c', '#bd0026', '#800026', '#66001a']
    
    if value is None:
        return '#999999'  # Default color for missing values
    for i, threshold in enumerate(deciles):
        if value <= threshold:
            return colors[i]
    return colors[-1]  # Use the last color for values in the highest decile

def create_distribution_plot(census_data, variables, var_name, normalization):
    """
    Creates a distribution plot for a specified census variable.

    Parameters
    ----------
    census_data : pandas.DataFrame
        The census data containing variables of interest.
    variables : list of str
        The census variables to include in the plot.
    var_name : str
        The name of the variable to be plotted.
    normalization : str
        Indicates whether the data should be normalized.

    Returns
    -------
    plotly.graph_objs.Figure
        The figure object containing the distribution plot.
    """
    # Create distplot with custom bin_size
    if normalization == 'Yes':
        dist_data = census_data[census_data[variables[0]]>0]['population_normalized']
        label = var_name+' (Population Normalized)'
    else:
        dist_data = census_data[census_data[variables[0]]>0][variables[0]]
        label = var_name
    fig = ff.create_distplot([dist_data], group_labels = [label])
    fig.update_layout(legend=dict(orientation="h",
                                    yanchor="bottom",
                                    y=1.02,
                                    xanchor="right",
                                    x=1
                                    )
    )
    return fig

def fetch_poi_within_catchment(catchment_polygon, poi_tags):
    """
    Fetch points of interest within a specified catchment area polygon and category.

    Parameters
    ----------
    catchment_polygon: 
        A Shapely Polygon defining the catchment area.
    poi_tags: 
        A dictionary representing the OSM group and categories of interest (e.g., {'amenity':['cafe', 'restaurant']}).

    Returns:
    -------
    GeoDataFrame()
        GeoDataFrame containing the fetched POI data.
    """
    try:
        # Define the tags for OSM queries based on the specified category
        key = list(poi_tags.keys())[0]
        tags = {key: poi_tags[key]}
        
        # Attempt to fetch POIs within the catchment area polygon
        pois_gdf = ox.features_from_polygon(catchment_polygon, tags=tags)
        
        # Check if the returned GeoDataFrame is empty
        if pois_gdf.empty:
            print("No data returned for the specified category within the catchment area.")
            return gpd.GeoDataFrame()  # Return an empty GeoDataFrame
        
        return pois_gdf
    except Exception as e:
        print(f"An error occurred while fetching POIs: {e}")
        return gpd.GeoDataFrame()  
    
def plot_poi_data_on_map(session_state, map_type):
    """
    Plots POI data on a map, either as markers or a heatmap, based on the specified map type.
    
    Parameters
    ----------
    session_state : st.session_state
        The current session state object.
    map_type : str
        The type of map to plot ('POI markers' or 'Heatmap (POI density)').
    
    Returns
    -------
    folium.Map
        The map with POI data plotted.
    """
    # Create a map centered around the catchment area using the user-selected map layer
    map_center = [session_state.catchment_area.geometry.centroid.y, session_state.catchment_area.geometry.centroid.x]
    m = folium.Map(location=map_center, tiles=None, zoom_start=13)
    if session_state.tile_layer_type == 'WMS':
        session_state.tile_layer_value.add_to(m)
    else:
        m = folium.Map(location=[session_state.location.latitude, session_state.location.longitude], tiles=session_state.tile_layer_value, zoom_start=13)

    Fullscreen(position="topright", title="Expand me", title_cancel="Exit me", force_separate_button=True).add_to(m)
    folium.GeoJson(mapping(session_state.catchment_area.geometry), style_function=lambda x: {'color': 'blue', 'fill': False}).add_to(m)
    folium.Marker([session_state.catchment_area.location.latitude, session_state.catchment_area.location.longitude],
                  popup='Catchment Location', icon=folium.Icon(color='red', prefix='fa',icon='map-pin'), tooltip=session_state.catchment_area.address).add_to(m)
    if map_type == 'Heatmap (POI density)':
        heatmap_points = []
    
    for _, poi in session_state.catchment_area.poi_data.iterrows():
        poi_location = poi.geometry.centroid.coords[0]
        if map_type == 'POI markers':
            folium.Marker(location=[poi_location[1], 
                                    poi_location[0]], 
                                    popup=f"{poi.get('name', 'Unnamed')} - {', '.join(filter(None, [str(poi.get(field, '')) for field in ['addr:housenumber', 'addr:street', 'addr:city', 'addr:state', 'addr:postcode']]))}").add_to(m)
        elif map_type == 'Heatmap (POI density)':
            heatmap_points.append([poi_location[1], poi_location[0]])

    if map_type == 'Heatmap (POI density)':
        HeatMap(heatmap_points).add_to(m)
    m.fit_bounds(session_state.bounds)
    return m

def display_poi_counts(poi_tags, catchment_area):
    """
    Displays the total counts of POI locations by category.
    
    Parameters
    ----------
    poi_tags: 
        A dictionary representing the OSM group and categories of interest (e.g., {'amenity':['cafe', 'restaurant']}).
    catchment_area : CatchmentArea
        A catchment area object from the CatchmentArea class.

    Returns
    -------
    None
    """
    key = list(poi_tags.keys())[0]
    if not catchment_area.poi_data.empty:
        counts = catchment_area.poi_data[key].value_counts()
        for category, count in counts.items():
            st.write(f"`{category}`: {count} distinct locations | {np.round(((count / catchment_area.total_population) * 10000),2)} distinct locations per 10,000 persons")
    else:
        st.write("No POI data available.")

import plotly.express as px

@st.experimental_fragment
def plot_poi_bar_chart(catchment_area):
    """
    Plots a bar chart of POI data using Plotly.

    Parameters:
    - catchment_area (CatchmentArea): a catchment area object from the CatchmetnArea class.
    - metric_type (str): A string that determines the metric to be plotted. Can be 'location count' or 'locations per capita'.

    Returns:
    - fig (plotly.graph_objects.Figure): The Plotly figure object that can be displayed with fig.show().
    """

    metric_type = st.selectbox('Select Metric',['Location count','Locations per capita'], index=1)
    pois_gdf = catchment_area.poi_data

    if not pois_gdf.empty:
        plot_df = pois_gdf['name'].value_counts().to_frame('count').reset_index()

        if metric_type not in ['Location count', 'Locations per capita']:
            raise ValueError("Invalid metric type provided. Choose 'location count' or 'locations per capita'.")

        # Calculate the metric
        if metric_type == 'Locations per capita':
            plot_df['metric'] = (plot_df['count'] / catchment_area.total_population) * 10000
            x_title = "Locations per Capita (per 10,000 persons)"
        else:
            plot_df['metric'] = plot_df['count']
            x_title = "Location Count"

        # Create the plot
        fig = px.bar(plot_df, y='name', x='metric', orientation='h',
                    title="Points of Interest Analysis",
                    labels={'name': 'Location Name', 'metric': x_title},
                    height=600, width=800)
        
        # Filter the DataFrame to only include the top 20 locations based on the metric
        top_locations = plot_df.nlargest(20, 'metric')

        # Create the plot
        fig = px.bar(top_locations, y='name', x='metric', orientation='h',
                    title=f'Top 20 Points of Interest by {x_title}',
                    labels={'location_name': 'Location Name', 'metric': x_title},
                    height=600, width=800)
        fig.update_layout(yaxis={'categoryorder': 'total ascending'}, xaxis_title=x_title, yaxis_title="Location Name")
        st.plotly_chart(fig, use_container_width=True)