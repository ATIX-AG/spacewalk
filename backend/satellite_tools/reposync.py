#!/usr/bin/python -u
#
# Copyright (c) 2008--2010 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
# 
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation. 
#
import sys, os, time, grp
import hashlib
from optparse import OptionParser
from server import rhnPackage, rhnSQL, rhnChannel, rhnPackageUpload
from common import CFG, initCFG, rhnLog, fetchTraceback
from spacewalk.common import rhn_rpm
from spacewalk.common.checksum import getFileChecksum
from spacewalk.common.rhn_mpm import InvalidPackageError
from server.importlib.importLib import IncompletePackage
from server.importlib.backendOracle import OracleBackend
from server.importlib.packageImport import ChannelPackageSubscription


default_log_location = '/var/log/rhn/reposync/'
default_hash = 'sha256'

class RepoSync:
   
    parser = None
    type = None
    urls = None
    channel_label = None
    channel = None
    fail = False
    quiet = False
    regen = False

    def main(self):
        initCFG('server')
        db_string = CFG.DEFAULT_DB #"rhnsat/rhnsat@rhnsat"
        rhnSQL.initDB(db_string)
        (options, args) = self.process_args()

        log_filename = 'reposync.log'
        if options.channel_label:
            date = time.localtime()
            datestr = '%d.%02d.%02d-%02d:%02d:%02d' % (date.tm_year, date.tm_mon, date.tm_mday, date.tm_hour, date.tm_min, date.tm_sec)
            log_filename = options.channel_label + '-' +  datestr + '.log'
           
        rhnLog.initLOG(default_log_location + log_filename)
        #os.fchown isn't in 2.4 :/
        os.system("chgrp apache " + default_log_location + log_filename)


        quit = False
        if not options.url:
            if options.channel_label:
                # TODO:need to look at user security across orgs
                h = rhnSQL.prepare("""select s.source_url
                                      from rhnContentSource s,
                                           rhnChannelContentSource cs,
                                           rhnChannel c
                                     where s.id = cs.source_id
                                       and cs.channel_id = c.id
                                       and c.label = :label""")
                h.execute(label=options.channel_label)
                source_urls = h.fetchall_dict() or []
                if source_urls:
                    self.urls = [row['source_url'] for row in source_urls]
                else:
                    quit = True
                    self.error_msg("Channel has no URL associated")
        else:
            self.urls = [options.url]
        if not options.channel_label:
            quit = True
            self.error_msg("--channel must be specified")
        if options.label:
            self.error_msg("--label is obsoleted")
        if options.mirror:
            self.error_msg("--mirrorlist is obsoleted; mirrorlist is recognized automatically")

        self.log_msg("\nSync started: %s" % (time.asctime(time.localtime())))
        self.log_msg(str(sys.argv))


        if quit:
            sys.exit(1)

        self.type = options.type
        self.channel_label = options.channel_label
        self.fail = options.fail
        self.quiet = options.quiet
        self.channel = self.load_channel()

        if not self.channel or not rhnChannel.isCustomChannel(self.channel['id']):
            print "Channel does not exist or is not custom"
            sys.exit(1)

        for url in self.urls:
            plugin = self.load_plugin()(url, self.channel_label)
            self.import_packages(plugin, url)
        if self.regen:
            taskomatic.add_to_repodata_queue_for_channel_package_subscription(
                [self.channel_label], [], "server.app.yumreposync")
        self.print_msg("Sync complete")

    def process_args(self):
        self.parser = OptionParser()
        self.parser.add_option('-u', '--url', action='store', dest='url', help='The url to sync')
        self.parser.add_option('-c', '--channel', action='store', dest='channel_label', help='The label of the channel to sync packages to')
        self.parser.add_option('-t', '--type', action='store', dest='type', help='The type of repo, currently only "yum" is supported', default='yum')
        self.parser.add_option('-l', '--label', action='store_true', dest='label', help='Ignored; for compatibility with old versions')
        self.parser.add_option('-f', '--fail', action='store_true', dest='fail', default=False , help="If a package import fails, fail the entire operation")
        self.parser.add_option('-q', '--quiet', action='store_true', dest='quiet', default=False, help="Print no output, still logs output")
        self.parser.add_option('-m', '--mirrorlist', action='store_true', dest='mirror', default=False, help="Ignored; for compatibility with old versions. Mirrorlist is recognized automatically.")
        return self.parser.parse_args()

    def load_plugin(self):
        name = self.type + "_src"
        mod = __import__('satellite_tools.repo_plugins', globals(), locals(), [name])
        submod = getattr(mod, name)
        return getattr(submod, "ContentSource")
        
    def import_packages(self, plug, url):
        packages = plug.list_packages()
        to_link = []
        to_download = []
        self.print_msg("Repo " + url + " has " + str(len(packages)) + " packages.")
        for pack in packages:
                 if self.channel_label not in \
                     rhnPackage.get_channels_for_package([pack.name, \
                     pack.version, pack.release, pack.epoch, pack.arch]) and \
                     self.channel_label not in \
                     rhnPackage.get_channels_for_package([pack.name, \
                     pack.version, pack.release, '', pack.arch]):
                     to_download.append(pack)

        if len(to_download) == 0:
            self.print_msg("No new packages to download.")
        else:
            self.regen=True
        is_non_local_repo = (url.find("file://") < 0)
        for (index, pack) in enumerate(to_download):
            """download each package"""
            # try/except/finally doesn't work in python 2.4 (RHEL5), so here's a hack
            try:
                try:
                    self.print_msg(str(index+1) + "/" + str(len(to_download)) + " : "+ \
                          pack.getNVREA())
                    path = plug.get_package(pack)
                    self.upload_package(pack, path)
                    self.associate_package(pack)
                except KeyboardInterrupt:
                    raise
                except Exception, e:
                   self.error_msg(e)
                   if self.fail:
                       raise
                   continue
            finally:
                if is_non_local_repo:
                    os.remove(path)
    
    def upload_package(self, package, path):
        temp_file = open(path, 'rb')
        header, payload_stream, header_start, header_end = \
                rhnPackageUpload.load_package(temp_file)
        package.checksum_type = header.checksum_type()
        package.checksum = getFileChecksum(package.checksum_type, file=temp_file)
        pid =  rhnPackage.get_package_for_checksum(
                                  self.channel['org_id'],
                                  package.checksum_type, package.checksum)

        if pid is None:
            rel_package_path = rhnPackageUpload.relative_path_from_header(
                    header, self.channel['org_id'],
                    package.checksum_type, package.checksum)
            package_path = os.path.join(CFG.MOUNT_POINT,
                    rel_package_path)
            package_dict, diff_level = rhnPackageUpload.push_package(header,
                    payload_stream, package.checksum_type, package.checksum,
                    force=False,
                    header_start=header_start, header_end=header_end,
                    relative_path=rel_package_path, 
                    org_id=self.channel['org_id'])
        temp_file.close()

    def associate_package(self, pack):
        caller = "server.app.yumreposync"
        backend = OracleBackend()
        backend.init()
        package = {}
        package['name'] = pack.name
        package['version'] = pack.version
        package['release'] = pack.release
        package['epoch'] = pack.epoch
        package['arch'] = pack.arch
        package['checksum'] = pack.checksum
        package['checksum_type'] = pack.checksum_type
        package['channels']  = [{'label':self.channel_label, 
                                 'id':self.channel['id']}]
        package['org_id'] = self.channel['org_id']
        try:
           self._importer_run(package, caller, backend)
        except:
            package['epoch'] = ''
            self._importer_run(package, caller, backend)

        backend.commit()

    def _importer_run(self, package, caller, backend):
            importer = ChannelPackageSubscription(
                       [IncompletePackage().populate(package)],
                       backend, caller=caller, repogen=False)
            importer.run()


    def load_channel(self):
        return rhnChannel.channel_info(self.channel_label)


    def print_msg(self, message):
        rhnLog.log_clean(0, message)
        if not self.quiet:
            print message


    def error_msg(self, message):
        rhnLog.log_clean(0, message)
        if not self.quiet:
            sys.stderr.write(str(message) + "\n")

    def log_msg(self, message):
        rhnLog.log_clean(0, message)

    def short_hash(self, str):
        return hashlib.new(default_hash, str).hexdigest()[0:8]

class ContentPackage:

    def __init__(self):
        # map of checksums
        self.checksums = {}
        self.checksum_type = None
        self.checksum = None

        #unique ID that can be used by plugin
        self.unique_id = None

        self.name = None
        self.version = None
        self.release = None
        self.epoch = None
        self.arch = None

    def setNVREA(self, name, version, release, epoch, arch):
        self.name = name
        self.version = version
        self.release = release
        self.arch = arch
        self.epoch = epoch

    def getNVREA(self):
        if self.epoch:
            return self.name + '-' + self.version + '-' + self.release + '-' + self.epoch + '.' + self.arch
        else:
            return self.name + '-' + self.version + '-' + self.release + '.' + self.arch

