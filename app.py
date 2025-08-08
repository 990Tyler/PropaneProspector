import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup

# Simplified scraper function for Buffalo county using requests + BeautifulSoup
def extract_BUFFALO_permits(year):
    base_url = "http://gcs.co.buffalo.wi.us/GCSWebPortal/Search.aspx"
    session = requests.Session()

    # Step 1: GET initial page to get VIEWSTATE and other hidden fields
    r = session.get(base_url)
    soup = BeautifulSoup(r.text, "html.parser")

    def get_hidden(name):
        el = soup.find("input", {"id": name})
        return el["value"] if el else ""

    viewstate = get_hidden("__VIEWSTATE")
    eventvalidation = get_hidden("__EVENTVALIDATION")
    viewstategenerator = get_hidden("__VIEWSTATEGENERATOR")

    form_data = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": viewstate,
        "__VIEWSTATEGENERATOR": viewstategenerator,
        "__EVENTVALIDATION": eventvalidation,
        "ctl00$cphMainApp$PermitSearchCriteria1$DropDownListDepartment": "ZONING DEPARTMENT",
        "ctl00$cphMainApp$PermitSearchCriteria1$DropDownListAppType": "UDC Administration",
        "ctl00$cphMainApp$PermitSearchCriteria1$TextBoxYear": str(year),
        "ButtonPermitSearch": "Search",
    }

    r2 = session.post(base_url, data=form_data)
    soup2 = BeautifulSoup(r2.text, "html.parser")

    data = []

    def parse_table(soup):
        table = soup.find(id="ctl00_cphMainApp_GridViewPermitResults")
        if not table:
            return []

        rows = table.find_all("tr")[1:]  # Skip header row
        results = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            results.append({
                "Permit Type": cells[0].get_text(strip=True),
                "Parcel Number": cells[4].get_text(strip=True),
                "Owner": cells[6].get_text(strip=True),
                "Property Address": cells[7].get_text(strip=True)
            })
        return results

    data.extend(parse_table(soup2))

    # Pagination support: (basic, only next page)
    while True:
        # Extract __VIEWSTATE etc for next POST
        viewstate = get_hidden("__VIEWSTATE")
        eventvalidation = get_hidden("__EVENTVALIDATION")
        viewstategenerator = get_hidden("__VIEWSTATEGENERATOR")

        # Find pagination links
        links = soup2.select("#ctl00_cphMainApp_GridViewPermitResults tr td table tr td a")
        current_page_num = 1
        try:
            current_page_num = int(soup2.select_one("#ctl00_cphMainApp_GridViewPermitResults tr td table tr td span").text)
        except:
            pass

        next_page_target = None
        for a in links:
            try:
                page_num = int(a.text.strip())
                if page_num == current_page_num + 1:
                    href = a.get("href")
                    if "javascript:__doPostBack" in href:
                        start = href.find("'") + 1
                        end = href.find("'", start)
                        next_page_target = href[start:end]
                    break
            except:
                continue

        if not next_page_target:
            break

        form_data = {
            "__EVENTTARGET": next_page_target,
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategenerator,
            "__EVENTVALIDATION": eventvalidation,
            "ctl00$cphMainApp$PermitSearchCriteria1$DropDownListDepartment": "ZONING DEPARTMENT",
            "ctl00$cphMainApp$PermitSearchCriteria1$DropDownListAppType": "UDC Administration",
            "ctl00$cphMainApp$PermitSearchCriteria1$TextBoxYear": str(year),
        }

        r2 = session.post(base_url, data=form_data)
        soup2 = BeautifulSoup(r2.text, "html.parser")
        data.extend(parse_table(soup2))

    df = pd.DataFrame(data)

    # Add parcel info from ArcGIS API
    def get_parcel_info(parcel_id, county_name="BUFFALO"):
        url = "https://services3.arcgis.com/n6uYoouQZW75n5WI/arcgis/rest/services/Wisconsin_Statewide_Parcels/FeatureServer/0/query"
        params = {
            "where": f"PARCELID='{parcel_id}' AND CONAME='{county_name}'",
            "outFields": "LATITUDE,LONGITUDE,PSTLADRESS",
            "returnGeometry": "false",
            "f": "json"
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            attrs = resp.json()["features"][0]["attributes"]
            return attrs.get("LATITUDE"), attrs.get("LONGITUDE"), attrs.get("PSTLADRESS", "")
        except:
            return None, None, None

    if not df.empty:
        df["Latitude"], df["Longitude"], df["Mailing Address"] = zip(*df["Parcel Number"].map(get_parcel_info))
    else:
        df["Latitude"], df["Longitude"], df["Mailing Address"] = [], [], []

    return df

# Streamlit UI
st.title("Propane Prospector Permit Lookup")

county = st.selectbox("Select County", ["BUFFALO"])  # Extend here with other counties later
year = st.number_input("Enter Year", min_value=2000, max_value=2025, value=2024)

if st.button("Get Permits"):
    with st.spinner("Scraping permit data, please wait..."):
        if county == "BUFFALO":
            df = extract_BUFFALO_permits(year)
        else:
            st.error("County scraper not implemented yet.")
            df = pd.DataFrame()

        if df.empty:
            st.warning("No permit data found.")
        else:
            # Create clickable Google Maps link
            def map_link(row):
                addr = row["Property Address"]
                if pd.isna(addr):
                    return ""
                return f"[Map](https://maps.google.com/?q={addr.replace(' ', '+')})"

            df["Map Link"] = df.apply(map_link, axis=1)

            st.dataframe(df)

            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Download CSV", data=csv, file_name=f"{county}_permits_{year}.csv", mime="text/csv")
