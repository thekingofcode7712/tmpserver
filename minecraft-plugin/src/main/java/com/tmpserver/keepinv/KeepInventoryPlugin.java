package com.tmpserver.keepinv;

import java.util.UUID;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.plugin.java.JavaPlugin;

public final class KeepInventoryPlugin extends JavaPlugin implements Listener {
    private static final UUID OWNER_UUID = UUID.fromString("00000000-0000-0000-0009-01f5288246d8");

    @Override
    public void onEnable() {
        getServer().getPluginManager().registerEvents(this, this);
        getLogger().info("Per-player keep inventory enabled for .BroodyFoil99867 (" + OWNER_UUID + ")");
    }

    @EventHandler
    public void onPlayerDeath(PlayerDeathEvent event) {
        if (!OWNER_UUID.equals(event.getPlayer().getUniqueId())) return;
        event.setKeepInventory(true);
        event.setKeepLevel(true);
        event.getDrops().clear();
        event.setDroppedExp(0);
        getLogger().info("Kept inventory and experience for " + event.getPlayer().getName());
    }
}
