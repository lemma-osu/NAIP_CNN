import ee

from naip_cnn.config import CRS


class Acquisition:
    """A LiDAR aquisition with associated NAIP imagery in Earth Engine."""

    def __init__(self, name: str, start_date: str, end_date: str) -> None:
        self.name = name
        self.start_date = start_date
        self.end_date = end_date

    @property
    def proj(self):
        return ee.Projection(CRS)

    @property
    def geometry(self):
        return ee.Image(
            f"projects/ee-maptheforests/assets/malheur_lidar/{self.name}"
        ).geometry()

    @property
    def mask(self):
        """A mask of fast loss over the acqusition period."""
        return (
            ee.ImageCollection("USFS/GTAC/LCMS/v2022-8")
            .filter(ee.Filter.eq("study_area", "CONUS"))
            .filterDate(self.start_date, self.end_date)
            .select("Change")
            .map(lambda img: img.eq(3))
            .max()
            .eq(0)
            .reproject(self.proj.atScale(30))
        )

    def load_naip(self):
        return (
            ee.ImageCollection("USDA/NAIP/DOQQ")
            .filterDate(self.start_date, self.end_date)
            .filterBounds(self.geometry.bounds())
            .mosaic()
            .updateMask(self.mask)
            .reproject(self.proj.atScale(1))
        )

    def load_lidar(self):
        return (
            ee.Image(f"projects/ee-maptheforests/assets/malheur_lidar/{self.name}")
            .updateMask(self.mask)
            .reproject(self.proj.atScale(30))
        )


# OR NAIP years: 2004 (RGB), 2005 (RGB), 2009, 2011, 2012, 2014, 2016, 2020, 2022
MAL2007 = Acquisition(name="MAL2007", start_date="2007-01-01", end_date="2009-12-31")
MAL2008_CampCreek = Acquisition(
    name="MAL2008_CampCreek", start_date="2008-01-01", end_date="2009-12-31"
)
MAL2008_2009_MalheurRiver = Acquisition(
    name="MAL2008_2009_MalheurRiver", start_date="2008-01-01", end_date="2009-12-31"
)
MAL2010 = Acquisition(name="MAL2010", start_date="2010-01-01", end_date="2011-12-31")
MAL2014 = Acquisition(name="MAL2014", start_date="2014-01-01", end_date="2014-12-31")
MAL2016_CanyonCreek = Acquisition(
    name="MAL2016_CanyonCreek", start_date="2016-01-01", end_date="2016-12-31"
)
MAL2017_Crow = Acquisition(
    name="MAL2017_Crow", start_date="2016-01-01", end_date="2017-12-31"
)
MAL2017_JohnDay = Acquisition(
    name="MAL2017_JohnDay", start_date="2016-01-01", end_date="2017-12-31"
)
MAL2018_Aldrich_UpperBear = Acquisition(
    name="MAL2018_Aldrich_UpperBear", start_date="2018-01-01", end_date="2020-12-31"
)
MAL2018_Rattlesnake = Acquisition(
    name="MAL2018_Rattlesnake", start_date="2018-01-01", end_date="2020-12-31"
)
MAL2019 = Acquisition(name="MAL2019", start_date="2019-01-01", end_date="2020-12-31")
MAL2020_UpperJohnDay = Acquisition(
    name="MAL2020_UpperJohnDay", start_date="2020-01-01", end_date="2020-12-31"
)