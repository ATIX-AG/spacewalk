--
-- Copyright (c) 2008--2010 Red Hat, Inc.
--
-- This software is licensed to you under the GNU General Public License,
-- version 2 (GPLv2). There is NO WARRANTY for this software, express or
-- implied, including the implied warranties of MERCHANTABILITY or FITNESS
-- FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
-- along with this software; if not, see
-- http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
-- 
-- Red Hat trademarks are not licensed under GPLv2. No permission is
-- granted to use or replicate Red Hat trademarks that are incorporated
-- in this software or its documentation. 
--
--
--
--

insert into rhnCryptoKeyType(id, label, description) values
	(sequence_nextval('rhn_cryptokeytype_id_seq'),'GPG','GPG');
insert into rhnCryptoKeyType(id, label, description) values
	(sequence_nextval('rhn_cryptokeytype_id_seq'),'SSL','SSL');

commit;

--
--
-- Revision 1.1  2003/11/13 15:29:17  pjones
-- bugzilla: 109896 -- add schema to hold cryptographic keys
--
