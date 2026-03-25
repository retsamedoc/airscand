Reverse Engineering the Apple Airscan / eSCL Protocol

I am not certain of the origins, one person involved in IPP printing claimed it was proprietary of HP , but then again they have their own protocol. AirScan/eSCL is used by other manufacturers too like Xerox, Kyocera, Canon and more. Mopria also seems to claim some responsibility for it but then again it seems not completely. In any case it seems shrouded in such secrecy that to date several years after its implementation, unless someone wants to take it all apart.

I offer this as my contribution. It is not perfect but almost there.

As I began looking for information to make a scanner more compatible, I could only find fragments of information. Even Apple Developer Forums offered zero help. 

Server/Client in eSCL / AirScan:
There is a “server”and a “client” the client can be a desktop computer or mobile device. The server is a scanner or another device configured to emulate a hardware scanner, even a desktop computer. In my case I did this on Linux, so Linux is discussed here. Examples of clients are Mopria Android Client, Apple Airscan (OSX and iOS), VueScan also runs on Mac Linux or Windows and seems to have some level of eSCL built in. It seems to be the “easiest client to please” 

How does eSCL/Airscan work?

The basics:
Avahi / Bonjour Discovery (typical dscovery _uscan._tcp
Client GET ScannerStatus
Server responds with HTML/XML
GET ScannerCapabilities
Server responds with HTML/XML
(GET ScannerStatus) again optional before a scan
(Server responds with HTML/XML)
POST to ScanJobs  an xml file that conforms to available options in ScannerStatus received earlier.
Server replies to POST with 201 Created and Location: /path/to/file.
(GET ScannerStatus) again optional after a scan
(Server responds with HTML/XML "Processing")
(GET ScannerStatus) again optional after a scan
(Server responds with HTML/XML "Processing")
GET ScannerStatus so we can tell when the scan is ready
Server responds with HTML/XML JOB URI
Job downloaded from URI

More detail:

Of curse the first step in the process in a Bonjour advertisement. On Linux, we do this with avahi daemon.  Later we will get to formatting a file for that purpose.

After  the client queries Bonjour/Avahi devices a text record like the following is received. I am showing only IPV4 responses but IP v6 is identical , except for the address.

+  wlan2 IPv4 AirScanning@hostname                   _uscan._tcp          local
This provides basic information that there are scanning service (_uscan._tcp) at the server hostname

With Linux and Avahi when we use the –resolve option we see more information including the following. 

=  wlan2 IPv4 AirScanning@HDTVStreamersIn                   _uscan._tcp          local
   hostname = [HDTVStreamersIn.local]
   address = [192.168.121.1]
   port = [80]
   txt = ["txtvers=1" "ty=AirScanning" "pdl=application/octet-stream,image/jpeg,application/pdf" "note=AirScanning" "adminurl=http://HDTVStreamersIn.local/airscan.php" "vers=2.5" "representation=http://HDTVStreamersIn.local./images/AirScanIcon2.png" "rs=eSCL" "cs=grayscale,color" "is=platen,adf" "duplex=F"]

The above is important for a few reasons. It tells us the next place to query . The “rs” (resource?) text entry is eSCL, which means that our base URL is 
http://hostname.local:80/eSCL
We could also theoretically have more than one scanner at an IP each with its own Avahi/Bonjour advertisement and nique root URI defined in “rs”

The “:80” is not required in the above example unless it is a port other than port 80. Also I have yet to see how an https advertisement looks, but imagine it has a flag indicating “https” somewhere.. 

From that basename we add “/ScannerStatus” giving us
http://hostname.local:80/eSCL/ScannerStatus

If the scanner is not busy we will get something like :

```xml
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerStatus xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" xsi:schemaLocation="http://schemas.hp.com/imaging/escl/2011/05/03 eSCL.xsd">
<pwg:Version>2.0</pwg:Version>
<pwg:State>Stopped</pwg:State>
</scan:ScannerStatus>
```

Now when we make a GET request to the above URL to see what the scanner is capable of, and  we see something like:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerCapabilities xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" xsi:schemaLocation="http://schemas.hp.com/imaging/escl/2011/05/03 eSCL.xsd">
        <pwg:Version>2.0</pwg:Version>
	<pwg:MakeAndModel>AirScanning on DeviceName</pwg:MakeAndModel>
        <!--<pwg:SerialNumber>012345678ABCDEF</pwg:SerialNumber>
        <scan:UUID>574E4233-4A44-3428-3736-86A93E4FA59A</scan:UUID>-->
        <scan:AdminURI>http://hostname.local./airscan.php</scan:AdminURI>
	<scan:IconURI>http://hostname.local./images/AirScanIcon2.png</scan:IconURI>
        <scan:Platen>
                <scan:PlatenInputCaps>
                        <scan:MinWidth>300</scan:MinWidth>
                        <scan:MaxWidth>2550</scan:MaxWidth>
                        <scan:MinHeight>300</scan:MinHeight>
                        <scan:MaxHeight>4200</scan:MaxHeight>
                        <scan:MaxScanRegions>1</scan:MaxScanRegions>
                        <scan:SettingProfiles>
                                <scan:SettingProfile>
                                        <scan:ColorModes>
                                                <scan:ColorMode>RGB24</scan:ColorMode>
                                                <scan:ColorMode>Grayscale8</scan:ColorMode>
                                        </scan:ColorModes>
                                        <scan:ContentTypes>
                                                <pwg:ContentType>TextAndPhoto</pwg:ContentType>
                                        </scan:ContentTypes>
                                        <scan:DocumentFormats>
                                                <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
                                                <pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>
                                                <pwg:DocumentFormat>application/octet-stream</pwg:DocumentFormat>
                                                <scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>
                                                <scan:DocumentFormatExt>application/pdf</scan:DocumentFormatExt>
                                                <scan:DocumentFormatExt>application/octet-stream</scan:DocumentFormatExt>
                                        </scan:DocumentFormats>
                                        <scan:SupportedResolutions>
                                                <scan:DiscreteResolutions>
                                                        <scan:DiscreteResolution>
                                                                <scan:XResolution>300</scan:XResolution>
                                                                <scan:YResolution>300</scan:YResolution>
                                                        </scan:DiscreteResolution>
                                                        <scan:DiscreteResolution>
                                                                <scan:XResolution>600</scan:XResolution>
                                                                <scan:YResolution>600</scan:YResolution>
                                                        </scan:DiscreteResolution>
                                                </scan:DiscreteResolutions>
                                        </scan:SupportedResolutions>
                                        <scan:ColorSpaces>
                                                <scan:ColorSpace>sRGB</scan:ColorSpace>
                                        </scan:ColorSpaces>
                                </scan:SettingProfile>
                        </scan:SettingProfiles>
                        <scan:SupportedIntents>
                                <scan:Intent>Preview</scan:Intent>
                                <scan:Intent>TextAndGraphic</scan:Intent>
                                <scan:Intent>Document</scan:Intent>
                                <scan:Intent>Photo</scan:Intent>
                        </scan:SupportedIntents>
                        <scan:MaxOpticalXResolution>600</scan:MaxOpticalXResolution>
                        <scan:MaxOpticalYResolution>600</scan:MaxOpticalYResolution>
                </scan:PlatenInputCaps>
        </scan:Platen>
        <scan:eSCLConfigCap>
                <scan:StateSupport>
                        <scan:State>disabled</scan:State>
                        <scan:State>enabled</scan:State>
                </scan:StateSupport>
                <scan:ScannerAdminCredentialsSupport>true</scan:ScannerAdminCredentialsSupport>
        </scan:eSCLConfigCap>
```

This tells us the information that should be contained in our request.
We can then generate a simple scan request to POST  with minimal information.

Please note. In SOME cases there may be multiple ways to define the same capability. One example is 

<pwg:DocumentFormat> or <scan:DocumentFormatExt>
&
</scan:MaxWidth> or <pwg:Width>
&
</scan:MaxHeight> or <pwg:Height>

The above xml sections may or may not both be present in ScannerStatus, but it appears that some clients use them without regard to which is in ScannerStatus. If you are working on a client you should respect what is in Scanner Status. If you are working on a server you should prepare to accept these options even if different from this ScannerCapabilites offered. I suspect that there are other such options like color mode but as yet have not seen it happen. 

What the Scanner Status XML means:
The ScannerCapabilities xml above indicates nothing of ADF or Feeder, so it is flatbed only
Supported resolutions afe 300x300 and 600x600 DPI
Supported formats are JPG, PDF and oclet-stream (this last one is apparently required for Apple compatibility)
We can scan with the following intentions; Preview, Text and Graphic, Photo and Document. On some scanners , scanning with Document intent for instance may initiate a Black and white scan.
We have color modes Grayscale8 and RGB24 available
MaxWidth/Height defines the maximum scan area  at 300 DPI.
MinWidth/Height defines the minimum scan area at 300 DPI.
This xml example does not have<pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>, which I suspect may affect the measurenet unit of Min and max height and width
Because this is a flatbed scanner some apps like Image Capture in OSX will start with a preview image, so once the scanner is selected it is already acquiring this preview. This allows us to select a limited part of the platen if for instance we have a small photo. This ScannerCapabilities xml file tells us we can select a single scan region so we can not put 2 photos on the platen and scan themas separate files. When we select that scan region we pass those coordinates on to out ScanJob xml POST request.    


Now we can POST our XML which is derived from ScannerCapabilities, but we make adjustments for height , witdth and select the resolution from those offered in ScannerStatus, etc.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
   <pwg:Version>2.0</pwg:Version>
   <pwg:ScanRegions>
      <pwg:ScanRegion>
         <pwg:Height>2100</pwg:Height>
         <pwg:Width>1500</pwg:Width>
         <pwg:XOffset>0</pwg:XOffset>
         <pwg:YOffset>0</pwg:YOffset>
      </pwg:ScanRegion>
   </pwg:ScanRegions>
   <scan:DocumentFormatExt>application/pdf</scan:DocumentFormatExt>
   <pwg:ContentType>TextAndPhoto</pwg:ContentType>
   <scan:XResolution>600</scan:XResolution>
   <scan:YResolution>600</scan:YResolution>
   <scan:ColorMode>Grayscale8</scan:ColorMode>
</scan:ScanSettings>
```
Because we selected the scan area and our image is pushed to the upper left of the platen X=0 and Y=0 we will be doing some cropping from that point rather than scanning the entire platen. Doing the math in the xml above our image should scan to 4100px H x 3000px W, as max width/height is expressed iat 300 DPI and we are scanning at 600 DPI .

Once the above is POSTed from client to server we then we get a response 201Created back as well as Location /escl/Scans/UNIQUE_ID.

Now we need to start checking ScannerStatus and might well see something like:
```xml
<?xml version="1.0" encoding="UTF-8"?> 
<scan:ScannerStatus xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" xsi:schemaLocation="http://schemas.hp.com/imaging/escl/2011/05/03 eSCL.xsd">
<pwg:Version>2.0</pwg:Version>
<pwg:State>Processing</pwg:State>
<scan:Jobs>
<scan:JobInfo>
<pwg:JobUri>/eSCL/Scans/UNIQUE_ID'</pwg:JobUri>
<pwg:JobUuid>UUID</pwg:JobUuid>
<pwg:JobState>Processing</pwg:JobState>
<pwg:ImagesToTransfer>0</pwg:ImagesToTransfer>
<pwg:ImagesCompleted>0</pwg:ImagesCompleted>
<pwg:JobStateReasons>
<pwg:JobStateReason>Processing</pwg:JobStateReason>
</pwg:JobStateReasons>
</scan:JobInfo>
</scan:Jobs>
</scan:ScannerStatus>
```
(here is where things get a little fuzzy and we have trouble keeping ALL clients happy! If you know the missing sauce from this point on please open a ticket. )

once the xml changes to something like
```xml
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerStatus xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" xsi:schemaLocation="http://schemas.hp.com/imaging/escl/2011/05/03 eSCL.xsd">
<pwg:Version>2.0</pwg:Version>
<pwg:State>Idle</pwg:State>
<scan:Jobs>
<scan:JobInfo>
<pwg:JobUri>/eSCL/Scans/UNIQUE_ID</pwg:JobUri>
<pwg:JobUuid>UUID</pwg:JobUuid>
<scan:Age>2</scan:Age>
<pwg:JobState>Completed</pwg:JobState>
<pwg:ImagesToTransfer>1</pwg:ImagesToTransfer>
<pwg:ImagesCompleted>1</pwg:ImagesCompleted>
<pwg:JobStateReasons>
<pwg:JobStateReason>JobCompletedSuccessfully</pwg:JobStateReason>
</pwg:JobStateReasons>
</scan:JobInfo>
</scan:Jobs>
</scan:ScannerStatus>
```

 Now the client SHOULD(!?) go and download the file from the URL and display & save it.

Some clients send a “DELETE” command after downloading but PWG claims a scanned document should be kept available for 300 seconds after scan completion 

Resources (not all is completely relevant):

http://testcluster.blogspot.com/2014/03/scanning-from-escl-device-using-command.html
http://testcluster.blogspot.com/2014/03/scanning-from-apple-airprint-airscan.html
http://www.pwg.org
https://mamascode.wordpress.com/2015/04/07/scanning-from-wifi-hp-scanner
https://github.com/kno10/python-scan-eSCL
https://github.com/SimulPiscator/AirSane
https://github.com/Ordissimo/scangearmp2/issues/7
https://h30434.www3.hp.com/t5/Scanning-Faxing-and-Copying/M277DW-Not-Scanning-macOS-Sierra-10-12-4/td-p/6054210/page/3



Here is the uscan.service file i use in /etc/avahi/services and some explanation. The <txt-record>representation causes an icon to show in Mopria and a somewhat greyed out icon in OSX Image Capture. Because Ihave tested on a customized version of Apache with PHP I use port 80, but use what you want. I set the adminurl to the web GUI.

```xml
<?xml version="1.0" standalone='no'?><!--*-nxml-*-->
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
<name replace-wildcards="yes">AirScanning@%h</name>
<service>
<type>_uscan._tcp</type>
<port>80</port>
<txt-record>duplex=F</txt-record>
<txt-record>is=platen,adf</txt-record>
<txt-record>cs=binary,grayscale,color</txt-record>
<txt-record>rs=eSCL</txt-record>
<txt-record>representation=http://HDTVStreamersIn.local./images/AirScanIcon2.png</txt-record>
<txt-record>vers=2.0</txt-record>
<txt-record>adminurl=http://HDTVStreamersIn.local/airscan.php</txt-record>
<txt-record>note=AirScanning</txt-record>
<txt-record>pdl=application/octet-stream,image/jpeg,application/pdf</txt-record>
<txt-record>ty=AirScanning</txt-record>
<txt-record>txtvers=1</txt-record>
</service>
</service-group>
```