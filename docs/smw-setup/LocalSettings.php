<?php
# =========================================================
# NanoClaw Knowledge Base — LocalSettings.php
# MediaWiki 1.43 + SemanticMediaWiki 6.0
# =========================================================

## Site identity
$wgSitename = "NanoClaw Knowledge Base";
$wgMetaNamespace = "Project";

## Server settings (update with your actual host/IP)
$wgServer = "http://192.168.1.235:8080";
$wgScriptPath = "";
$wgResourceBasePath = $wgScriptPath;

## Database
$wgDBtype = "mysql";
$wgDBserver = "db";
$wgDBname = "mediawiki";
$wgDBuser = "wikiuser";
$wgDBpassword = "wikipass";
$wgDBprefix = "";

## Secret keys (regenerate these!)
$wgSecretKey = "CHANGE_ME_generate_with_openssl_rand_hex_32";
$wgUpgradeKey = "CHANGE_ME_generate_with_openssl_rand_hex_8";

## Uploads
$wgEnableUploads = true;
$wgUseImageMagick = false;

## Language
$wgLanguageCode = "en";

## Cache
$wgCacheDirectory = "/tmp/mediawiki_cache";

## Extensions — load SMW BEFORE others
wfLoadExtension( 'SemanticMediaWiki' );
enableSemantics( 'localhost' );  # Change to your domain

## Additional SMW extensions
wfLoadExtension( 'SemanticResultFormats' );
# wfLoadExtension( 'PageForms' );  # Uncomment when installed

## SMW Configuration
$smwgQMaxDepth = 6;                    # Query depth for linked data
$smwgQMaxInlineLimit = 500;            # Max inline results
$smwgEnableUpdateJobs = true;          # Background semantic updates

## =========================================================
## NanoClaw Custom Namespaces
## =========================================================
## Custom namespace for Projects
define( 'NS_PROJECT_CUSTOM', 3000 );
define( 'NS_PROJECT_CUSTOM_TALK', 3001 );
$wgExtraNamespaces[NS_PROJECT_CUSTOM] = 'NanoClaw';
$wgExtraNamespaces[NS_PROJECT_CUSTOM_TALK] = 'NanoClaw_talk';

## =========================================================
## Permissions — open for local use, restrict as needed
## =========================================================
$wgGroupPermissions['*']['read'] = true;
$wgGroupPermissions['*']['edit'] = true;
$wgGroupPermissions['*']['createaccount'] = false;

## SMW admin access for sysop (Admin user)
$wgGroupPermissions['sysop']['smw-admin'] = true;

## =========================================================
## URL Protocols
## =========================================================
## Remove 'news:' so [[News:...]] wikilinks resolve to the News namespace
## instead of being parsed as NNTP newsgroup external URLs.
$wgUrlProtocols = array_diff($wgUrlProtocols, ['news:']);

## =========================================================
## Skin
## =========================================================
wfLoadSkin( 'Vector' );
$wgDefaultSkin = "vector";
