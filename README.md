Script to auto configure a docker worker and have it connect to rancher on amazon AWS.

Requirements:
Worker needs Config_Bucket and Config_Path tags pointing to a rancher-secrets.json file on S3.
The rancher-secrets.json should contain the following elements, json encoded:
* rancher_url
* rancher_key
* rancher_secret
