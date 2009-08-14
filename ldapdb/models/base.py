# -*- coding: utf-8 -*-
# 
# django-ldapdb
# Copyright (C) 2009 Bolloré telecom
# See AUTHORS file for a full list of contributors.
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

# -*- coding: utf-8 -*-

import ldap
import logging

import django.db.models

import ldapdb
from ldapdb.models.query import QuerySet

class ModelBase(django.db.models.base.ModelBase):
    """
    Metaclass for all LDAP models.
    """
    def __new__(cls, name, bases, attrs):
        attr_meta = attrs.pop('Ldap', None)

        super_new = super(ModelBase, cls).__new__
        new_class = super_new(cls, name, bases, attrs)

        # patch manager to use our own QuerySet class
        def get_query_set():
            return QuerySet(new_class)
        new_class.objects.get_query_set = get_query_set
        new_class._default_manager.get_query_set = get_query_set

        if attr_meta:
            new_class._meta.dn = attr_meta.dn
            new_class._meta.object_classes = attr_meta.object_classes

        return new_class

class Model(django.db.models.base.Model):
    """
    Base class for all LDAP models.
    """
    __metaclass__ = ModelBase

    dn = django.db.models.fields.CharField(max_length=200)

    def __init__(self, *args, **kwargs):
        super(Model, self).__init__(*args, **kwargs)
        self.saved_pk = self.pk

    def build_rdn(self):
        """
        Build the Relative Distinguished Name for this entry.
        """
        bits = []
        for field in self._meta.local_fields:
            if field.primary_key:
                bits.append("%s=%s" % (field.db_column, getattr(self, field.name)))
        if not len(bits):
            raise Exception("Could not build Distinguished Name")
        return '+'.join(bits)

    def build_dn(self):
        """
        Build the Distinguished Name for this entry.
        """
        return "%s,%s" % (self.build_rdn(), self._meta.dn)
        raise Exception("Could not build Distinguished Name")

    def delete(self):
        """
        Delete this entry.
        """
        logging.debug("Deleting LDAP entry %s" % self.dn)
        ldapdb.connection.delete_s(self.dn)
        
    def save(self):
        # create a new entry
        if not self.dn:
            entry = [('objectClass', self._meta.object_classes)]
            new_dn = self.build_dn()

            for field in self._meta.local_fields:
                if not field.db_column:
                    continue
                value = getattr(self, field.name)
                if value:
                    entry.append((field.db_column, value))

            logging.debug("Creating new LDAP entry %s" % new_dn)
            ldapdb.connection.add_s(new_dn, entry)
            
            # update object
            self.dn = new_dn
            self.saved_pk = self.pk
            return

        # update an existing entry
        modlist = []
        orig = self.__class__.objects.get(pk=self.saved_pk)
        for field in self._meta.local_fields:
            if not field.db_column:
                continue
            old_value = getattr(orig, field.name, None)
            new_value = getattr(self, field.name, None)
            if old_value != new_value:
                if new_value:
                    modlist.append((ldap.MOD_REPLACE, field.db_column, new_value))
                elif old_value:
                    modlist.append((ldap.MOD_DELETE, field.db_column, None))

        if not len(modlist):
            logging.debug("No changes to be saved to LDAP entry %s" % self.dn)
            return

        # handle renaming
        new_dn = self.build_dn()
        if new_dn != self.dn:
            logging.debug("Renaming LDAP entry %s to %s" % (self.dn, new_dn))
            ldapdb.connection.rename_s(self.dn, self.build_rdn())
            self.dn = new_dn
    
        logging.debug("Modifying existing LDAP entry %s" % self.dn)
        ldapdb.connection.modify_s(self.dn, modlist)
        self.saved_pk = self.pk

