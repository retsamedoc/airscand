"""XML namespace URIs and SOAP action constants shared across WSD / WS-Scan / WS-Eventing."""

# SOAP 1.2
NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
# WS-Addressing 2004/08 (required for tested hardware; W3C 2005/08 broke Subscribe on Epson-class devices).
NS_WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
NS_WSE = "http://schemas.xmlsoap.org/ws/2004/08/eventing"
NS_WST = "http://schemas.xmlsoap.org/ws/2004/09/transfer"
NS_SCA = "http://schemas.microsoft.com/windows/2006/08/wdp/scan"
NS_WSMAN = "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"

NS_WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
NS_WSDP = "http://schemas.xmlsoap.org/ws/2006/02/devprof"
NS_PUB = "http://schemas.microsoft.com/windows/pub/2005/07"
NS_WSCN = "http://schemas.microsoft.com/windows/2006/08/wdp/scan"

NS_WSA_ROLE_ANONYMOUS = "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous"

WSA_ANONYMOUS = f"{NS_WSA}/role/anonymous"

FILTER_DIALECT_DEVPROF_ACTION = "http://schemas.xmlsoap.org/ws/2006/02/devprof/Action"
SCAN_AVAILABLE_EVENT_ACTION = f"{NS_SCA}/ScanAvailableEvent"
SCANNER_STATUS_SUMMARY_EVENT_ACTION = f"{NS_SCA}/ScannerStatusSummaryEvent"

ACTION_SUBSCRIBE = f"{NS_WSE}/Subscribe"
ACTION_RENEW = f"{NS_WSE}/Renew"
ACTION_UNSUBSCRIBE = f"{NS_WSE}/Unsubscribe"
ACTION_GET = f"{NS_WST}/Get"
ACTION_VALIDATE_SCAN_TICKET = f"{NS_SCA}/ValidateScanTicket"
ACTION_CREATE_SCAN_JOB = f"{NS_SCA}/CreateScanJob"
ACTION_RETRIEVE_IMAGE = f"{NS_SCA}/RetrieveImage"
ACTION_GET_SCANNER_ELEMENTS = f"{NS_SCA}/GetScannerElements"
ACTION_GET_JOB_STATUS = f"{NS_SCA}/GetJobStatus"

ACTION_PROBE = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe"
ACTION_RESOLVE = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Resolve"
ACTION_PROBE_MATCHES = "http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches"
ACTION_RESOLVE_MATCHES = "http://schemas.xmlsoap.org/ws/2005/04/discovery/ResolveMatches"
ACTION_HELLO = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Hello"
ACTION_BYE = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Bye"
