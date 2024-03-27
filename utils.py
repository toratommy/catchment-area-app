import streamlit as st
import folium
from geopy.geocoders import Nominatim
import pandas as pd
import requests
import geopandas as gpd
from shapely.geometry import Point, shape
from shapely.ops import transform
import pyproj
from functools import partial
from census import Census
from scipy import *
import plotly.figure_factory as ff
import osmnx as ox
from folium.plugins import HeatMap
from shapely.geometry import mapping

def draw_circle(catchment_map, location, radius):
    """Draw a circle on the map."""
        
        # Create a point from the location
    point = Point(location.longitude, location.latitude)
        
    # Create circle buffer around the point and transform back to WGS84
    circle_poly = point.buffer(radius)  # buffer in projected crs units (meters)
    
    # Use a Lambert Azimuthal Equal Area projection to approximate the circle on the Earth's surface
    az_ea_proj = partial(
        pyproj.transform,
        pyproj.Proj(f'+proj=aeqd +lat_0={location.latitude} +lon_0={location.longitude} +x_0=0 +y_0=0'),
        pyproj.Proj('+proj=longlat +datum=WGS84')
    )
    
    # Create circle buffer around the point and transform back to WGS84
    circle_poly = transform(az_ea_proj, point.buffer(radius))  # buffer in projected crs units (meters)
    circle = folium.GeoJson(circle_poly, style_function=lambda x:{'fillColor': 'black', 'color': 'black'})
    circle.add_to(catchment_map)
    bounds = circle.get_bounds()
    catchment_map.fit_bounds(bounds)
    return circle_poly, bounds

def draw_drive_time_area(catchment_map, location, drive_time, client):
    """Draw an area based on drive time."""
    coordinates = [[location.longitude, location.latitude]]
    params = {
        'locations': coordinates,
        'range': [drive_time * 60],  # Convert minutes to seconds
        'range_type': 'time'
    }
    response_iso = client.isochrones(**params)
    response_poly = shape(response_iso['features'][0]['geometry'])
    polygon = folium.GeoJson(response_iso, style_function=lambda x:{'fillColor': 'black', 'color': 'black'})
    polygon.add_to(catchment_map)

    bounds = polygon.get_bounds()
    catchment_map.fit_bounds(bounds)
    return response_poly, bounds

def geocode_address(address):
    """Geocode an address using Nominatim."""
    geolocator = Nominatim(user_agent="streamlit_catchment_app")
    try:
        return geolocator.geocode(address)
    except:
        return None
    
def fetch_census_variables(api_url):
    """
    Fetch the variables.json from the Census API.

    :param api_url: The base URL for the Census API endpoint containing the variables.json file.
    :return: A dictionary containing the variables and their metadata, or None if the fetch fails.
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
        return variables_df
    except requests.RequestException as e:
        print(f"Failed to fetch variables.json: {e}")
        return None
    
def load_state_boundaries(census_year):
    """
    Load state boundaries using the US Census Bureau's cartographic boundary files.
    """
    url = "https://www2.census.gov/geo/tiger/GENZ{0}/shp/cb_{0}_us_state_20m.zip".format(census_year)
    gdf = gpd.read_file(url)
    return gdf

def find_intersecting_states(user_gdf, states_gdf):
    """
    Find states that intersect with the user-defined geography.
    """
    intersecting_states = states_gdf[states_gdf.intersects(user_gdf.unary_union)]
    return intersecting_states['GEOID']

def load_tract_shapefile(state_code, census_year):
    """
    Load a census tract shapefile directly from the Census website for a given state code.
    """
    url = f"https://www2.census.gov/geo/tiger/TIGER{census_year}/TRACT/tl_{census_year}_{state_code}_tract.zip"
    gdf = gpd.read_file(url)
    return gdf

def calculate_overlapping_tracts(user_gdf, state_codes, census_year):
    """
    Calculate which tracts overlap with the user-defined geography for the intersecting states,
    considering a tract as overlapping only if >50% of its area is covered by the user geo.
    """
    overlapping_tracts = gpd.GeoDataFrame()
    for state_code in state_codes:
        tract_gdf = load_tract_shapefile(state_code, census_year)
        
        # Calculate the intersection area between each tract and the user-defined geography
        tract_gdf['intersection_area'] = tract_gdf.geometry.apply(lambda x: x.intersection(user_gdf.unary_union).area)
        
        # Calculate the percentage of each tract covered by the user-defined geography
        tract_gdf['coverage_percentage'] = (tract_gdf['intersection_area'] / tract_gdf.geometry.area) * 100
        
        # Filter tracts where the coverage percentage is greater than 30%
        tracts_overlapping = tract_gdf[tract_gdf['coverage_percentage'] > 30]
        
        overlapping_tracts = pd.concat([overlapping_tracts, tracts_overlapping])

    # Drop the temporary columns used for calculations
    overlapping_tracts = overlapping_tracts.drop(columns=['intersection_area', 'coverage_percentage'])

    return overlapping_tracts

def fetch_census_data_for_tracts(census_api, census_year, variables, overlapping_tracts, normalization):
    """
    Fetch census data in batches for all tracts within each state/county in the overlapping_tracts dataframe.
    Then, filter the resulting fetched data to only include tracts that are indeed overlapping.
    """
    # Prepare an empty DataFrame to hold fetched census data
    all_census_data = pd.DataFrame()

    # Group the overlapping tracts by state and county for batch fetching
    for (state_code, county_code), group in overlapping_tracts.groupby(['STATEFP', 'COUNTYFP']):
        # Fetch census data for all tracts within this state and county
        if normalization == 'Yes':
            fetch_vars = variables+['B01003_001E']
        else:
            fetch_vars = variables
        
        tracts_data = census_api.acs5.state_county_tract(fetch_vars, state_code, county_code, Census.ALL, year=census_year)
        # Convert the fetched data into a DataFrame
        tracts_df = pd.DataFrame(tracts_data)
        
        # Convert GEOID to a format that matches the overlapping_tracts for comparison
        tracts_df['GEOID'] = tracts_df.apply(lambda row: f"{row['state']}{row['county']}{row['tract']}", axis=1)
        
        # Filter the data to only include those tracts that are in the overlapping_tracts DataFrame
        tracts_df = tracts_df[tracts_df['GEOID'].isin(overlapping_tracts['GEOID'])]
        
        # Append the filtered data to the all_census_data DataFrame
        all_census_data = pd.concat([all_census_data, tracts_df], ignore_index=True)
        if normalization == 'Yes':
            all_census_data['population_normalized'] = all_census_data[variables[0]]/all_census_data['B01003_001E']

    return all_census_data

def plot_census_data_on_map(catchment_map, bounds, overlapping_tracts_gdf, census_data, census_variable, var_name, normalization):
    """
    Plot tracts on a Folium map, colored by a specified census variable.
    
    :param overlapping_tracts_gdf: GeoDataFrame containing the geometries of the tracts.
    :param census_data: DataFrame containing the census data for the tracts.
    :param census_variable: The census variable to color the tracts by.
    """
    # Merge the census data with the tract geometries
    merged_data = overlapping_tracts_gdf.merge(census_data, left_on='GEOID', right_on='GEOID')

    # Convert to GeoJSON
    geojson_data = merged_data.to_json()
    
    if normalization == 'Yes':
        plot_var = 'population_normalized'
        alias = var_name+' (Population Normalized):'
        deciles = merged_data['population_normalized'].quantile([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]).to_list()
    else:
        plot_var = census_variable
        alias = var_name+':'
        deciles = merged_data[census_variable].quantile([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]).to_list()
    
    # Add the GeoJSON layer to the map
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
    ).add_to(catchment_map)
    catchment_map.fit_bounds(bounds)
    


def get_color(value, deciles):
    """
    Determine color based on which decile the value falls into.
    """
    colors = ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c',
              '#fc4e2a', '#e31a1c', '#bd0026', '#800026', '#66001a']
    
    if value is None:
        return '#999999'  # Default color for missing values
    for i, threshold in enumerate(deciles):
        if value <= threshold:
            return colors[i]
    return colors[-1]  # Use the last color for values in the highest decile

def calculate_area_sq_miles(user_poly):
    proj = partial(pyproj.transform,
                   pyproj.Proj(init='epsg:4326'),  # Source coordinate system (WGS84)
                   pyproj.Proj(proj='aea', lat_1=user_poly.bounds[1], lat_2=user_poly.bounds[3]))  # Albers Equal Area projection
    projected_polygon = transform(proj, user_poly) 
     # Project the polygon to the new coordinate system
    area_sq_miles = round(projected_polygon.area / 2589988.11,2)  # Convert area from square meters to square miles
    return area_sq_miles

def create_distribution_plot(census_data, variables, var_name, normalization):
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

def fetch_poi_within_catchment(catchment_polygon, category):
    """
    Fetch points of interest within a specified catchment area polygon and category.

    Parameters:
    - catchment_polygon: A Shapely Polygon defining the catchment area.
    - category: A string representing the OSM category of interest (e.g., 'cafe', 'restaurant').

    Returns:
    - GeoDataFrame containing the fetched POIs.
    """
    try:
        # Define the tags for OSM queries based on the specified category
        tags = {'amenity': category}
        
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

def plot_poi_data_on_map(pois_gdf, catchment_polygon, map_type):
    # Create a map centered around the catchment area
    map_center = [catchment_polygon.centroid.y, catchment_polygon.centroid.x]
    m = folium.Map(location=map_center, zoom_start=13)
    
    # Add the catchment area boundary to the map
    folium.GeoJson(mapping(catchment_polygon), style_function=lambda x: {'color': 'black', 'fill':False}).add_to(m)
    for _, poi in pois_gdf.iterrows():
        # Construct address string
        address_parts = [str(poi.get(field, '')) for field in ['addr:housenumber', 'addr:street', 'addr:city', 'addr:state', 'addr:postcode']]
        address = ', '.join(filter(None, address_parts))
        tooltip = f"{poi.get('name', 'Unnamed')} - {address}"
        
        poi_location = poi.geometry.centroid.coords[0]
        # Determine location based on geometry type
        #if poi.geometry.geom_type == 'Polygon' or poi.geometry.geom_type == 'MultiPolygon':
        #    poi_location = poi.geometry.centroid.coords[0]
        #else:  # Assume Point
        #    poi_location = (poi.geometry.y, poi.geometry.x)
        
        # Plot based on map_type
        if map_type == 'POI markers':
            folium.Marker(location=[poi_location[1], poi_location[0]], popup=tooltip).add_to(m)
        elif map_type == 'Heatmap (POI density)':
            if 'heatmap_points' not in locals():
                heatmap_points = []
            heatmap_points.append([poi_location[1], poi_location[0]])

        # Add heatmap layer if specified
        if map_type == 'Heatmap (POI density)':
            HeatMap(heatmap_points).add_to(m)

    return m

def display_poi_counts(pois_gdf):
    # Assuming 'amenity' column stores the POI category
    if not pois_gdf.empty and 'amenity' in pois_gdf.columns:
        counts = pois_gdf['amenity'].value_counts()
        for category, count in counts.items():
            st.write(f"{category}: {count} distinct locations")
            st.dataframe(pois_gdf[['amenity','name','addr:housenumber', 'addr:street', 'addr:city', 'addr:state', 'addr:postcode']])
    else:
        st.write("No POI data available.")

